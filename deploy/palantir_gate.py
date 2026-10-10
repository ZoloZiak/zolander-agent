#!/usr/bin/env python3
"""
palantir_gate_v2.py — ADAPTÍVNY per-model pacing reverse-proxy pred Palantir LLM proxy.

Nadstavba nad palantir_gate_adaptive.py. Zapracovaný research z congestion-control sveta
(Netflix concurrency-limits, Envoy adaptive_concurrency, AWS SDK adaptive retry, TCP Vegas).

ČO JE NOVÉ oproti v1 (palantir_gate_adaptive.py) — a PREČO:

  1) PER-MODEL STAV (najdôležitejšie). Palantir docs: rate limity sú per-model, nezávislé
     osi (RPM aj TPM). Jeden globálny semafor bol chyba — 429 na GPT zbytočne zabrzdil aj
     Claude. v2 drží samostatný AIMD stav pre KAŽDÝ model (kľúč = "model" z JSON tela,
     fallback = prefix cesty /anthropic|/openai|/google). GPT vetva sa škrtí nezávisle od Claude.

  2) FULL JITTER backoff (AWS re:Invent "Exponential Backoff and Jitter"). Namiesto fixného
     penalty okna, kde po expirácii všetci workeri nabehnú v tej istej ms (thundering herd),
     každý retry spí random(0, min(cap, base·2^attempt)). AWS namerali >50% menej volaní pri
     100 súbežných klientoch oproti nejitterovanému backoffu.

  3) RETRY TOKEN BUCKET (AWS dvoj-bucket dizajn). Zdieľaný retry budget per model. Každý retry
     minie token, úspech vráti token (bounded). Keď je bucket prázdny -> gate PRESTANE
     retryovať a error PREPUSTÍ. Bez toho by pri reálnom výpadku upstreamu gate retryoval
     donekonečna a zamaskoval trvalý problém (session by visela navždy).

  4) GROW-ONLY-WHEN-BUSY + sqrt headroom (Envoy gradient headroom, geofencing failure #3).
     Limit rastie LEN keď je reálne využívaný (inflight blízko limitu). Inak by počas ticha
     vyliezol na strop a prvý burst po pauze by zaplavil Palantir. Rast = sqrt(limit) štýl:
     rýchly keď je limit malý, stabilný keď veľký.

  ČO SME VEDOME NEZOBRALI (honest mirror — dokumentované, nech to niekto neprilepí "pre istotu"):
  - Vegas / Gradient2 LATENCY-based limit. Netflix ich odporúča SERVER-side. Pre náš
    CLIENT-side prípad pred treťostranným LLM API sú NEBEZPEČNÉ:
      * 429 od Palantiru príde za pár ms -> latency limiter to číta ako "najrýchlejší
        upstream v histórii" -> gradient≈1 -> ZDVIHNE limit -> nabehne rovno do stropu.
      * legitímny 45s streamovaný completion vyzerá ako "preťaženie" -> zbytočne zrezhe limit.
    LLM latencia ∝ dĺžka outputu, NIE hĺbka fronty. Preto ostávame pri LOSS-based AIMD na
    skutočnom 429 signáli — presne ako Netflix odporúča client-side (AIMDLimit).

Kompatibilita: rovnaké routovanie ako v1 (Hermes -> 127.0.0.1:PORT/<provider>/... -> Palantir),
rovnaká auth normalizácia (x-api-key -> Bearer), rovnaký multi-token round-robin, streaming.

Spustenie:
  python3 palantir_gate_v2.py --port 8787 --min-conc 1 --max-conc 8 --initial-conc 3

Test:
  curl -s http://127.0.0.1:8787/_gate/stats     # per-model breakdown
"""
import os, ssl, json, time, random, threading, argparse, http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── upstream (Palantir proxy) ────────────────────────────────────────────
UPSTREAM_HOST = os.environ.get("GATE_TEST_UPSTREAM_HOST", "tenant.region.palantirfoundry.example")
UPSTREAM_PORT = int(os.environ.get("GATE_TEST_UPSTREAM_PORT", 443))
UPSTREAM_BASE = "/api/v2/llm/proxy"
# test mód: mock beží ako plain HTTP na 127.0.0.1 -> vypni TLS
_TEST_UPSTREAM = "GATE_TEST_UPSTREAM_HOST" in os.environ

_CTX = ssl.create_default_context()

LOG_PATH = os.path.expanduser("~/.hermes/logs/palantir_gate.log")

_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade"}

_RATE_STATUS = {429}
_SERVER_STATUS = {500, 502, 503, 529}


class ModelGate:
    """Samostatný AIMD stav pre JEDEN model. Palantir limity sú per-model, takže každý
    model má vlastný limit, inflight, penalty okno a retry token bucket."""

    def __init__(self, name, cfg):
        self.name = name
        self.cfg = cfg
        self.cv = threading.Condition()
        # AIMD živá premenná
        self.limit = float(cfg["initial_conc"])
        self.inflight = 0
        self._sat_ok = 0                 # úspechy počas saturácie (grow-only-when-busy)
        self._penalty_until = 0.0
        self._spacing_until = 0.0        # v3.2: reaktívne spacing okno (aktívne len po 429)
        self._last_start = 0.0
        # ── ADAPTÍVNY SENDING RATE (v3 jadro) ─────────────────────────────
        # 429 od Palantiru je RATE limit (chodí aj pri concurrency=1), NIE concurrency
        # signál. Preto sa učí PRÁVE spacing medzi volaniami (AIMD na rate = 1/interval):
        #   úspech  -> rate += rate_inc (aditívny rast, "raz za interval" = mimic 1×/RTT)
        #   429     -> rate *= rate_dec (multiplikatívny prepad, prudké spomalenie)
        # Concurrency (self.limit) uz 429 NEKOLABUJE — ostáva len bezpečnostný strop.
        self.rate = float(cfg["initial_rate"])       # req/s, živá premenná
        self._last_rate_bump = 0.0
        self.rate_peak = self.rate
        self.rate_floor = self.rate
        # ── ADAPTÍVNY TPM BUDGET (v3.1 jadro — PRAVÁ páka) ─────────────────
        # Dôkaz (probe 2026-09-28): malé requesty prechádzajú, veľké dostávajú 429 pri
        # riedkom trafiku => Palantir strop je TPM (tokeny/min = VEĽKOSŤ), NIE RPM (počet).
        # Preto hlavná brzda = sliding-window tokenov za 60s proti ADAPTÍVNEMU budgetu:
        #   429  -> budget *= tpm_dec (nauč sa reálny TPM strop dole)
        #   200  -> budget += tpm_inc (opatrne dvíhaj späť)
        # Veľký request minie veľa budgetu -> ďalší počká; malý prejde hneď.
        self.tpm_budget = float(cfg["initial_tpm"])
        self._tpm_window = []            # zoznam (ts, tokens) za posledných 60s
        self._tpm_used = 0.0             # súčet tokenov v okne (rýchly lookup)
        self.tpm_peak = self.tpm_budget
        self.tpm_floor = self.tpm_budget
        # retry token bucket (AWS-style): zdieľaný retry budget
        self.retry_tokens = float(cfg["retry_bucket_max"])
        self._last_refill = time.time()
        # metriky
        self.total = 0
        self.forbidden = 0            # 403 Filter:RequestBlocked (egress IP mimo allowlistu)
        self.rl_hits = 0
        self.server_errs = 0
        self.retries = 0
        self.retries_denied = 0          # koľkokrát bucket zakázal retry (prepustili error)
        self.max_queue_wait = 0.0
        self.limit_peak = self.limit
        self.limit_floor = self.limit

    # ── retry token bucket ────────────────────────────────────────────────
    def _refill_locked(self):
        now = time.time()
        dt = now - self._last_refill
        if dt > 0:
            self.retry_tokens = min(self.cfg["retry_bucket_max"],
                                    self.retry_tokens + dt * self.cfg["retry_refill_per_s"])
            self._last_refill = now

    def try_take_retry_token(self):
        """Skús vziať token na retry. False => bucket prázdny => NEretryuj, prepusti error."""
        with self.cv:
            self._refill_locked()
            if self.retry_tokens >= 1.0:
                self.retry_tokens -= 1.0
                return True
            self.retries_denied += 1
            return False

    def give_back_retry_token(self):
        with self.cv:
            self.retry_tokens = min(self.cfg["retry_bucket_max"],
                                    self.retry_tokens + self.cfg["retry_success_credit"])

    # ── AIMD ──────────────────────────────────────────────────────────────
    def on_success(self, was_saturated):
        """HTTP 200. Dve nezávislé veci:
        (1) RATE additive increase — po úspechu jemne zrýchli sending rate (učí sa strop RPM).
            Krok raz za ~1/rate (mimic "1 prírastok za RTT" z AIMD), nie na každý request.
        (2) concurrency grow-only-when-busy (ako v2) — len bezpečnostný strop, sekundárny."""
        with self.cv:
            self.give_back_retry_token()
            # (1) adaptívny rate: additive increase, rate-limitovaný na ~1 bump / (1/rate)
            now = time.time()
            if now - self._last_rate_bump >= (1.0 / max(self.rate, 0.01)):
                self._last_rate_bump = now
                if self.rate < self.cfg["max_rate"]:
                    self.rate = min(self.cfg["max_rate"], self.rate + self.cfg["rate_inc"])
                    self.rate_peak = max(self.rate_peak, self.rate)
            # (1b) adaptívny TPM budget: opatrne dvíhaj po úspechu (additive increase)
            if self.cfg.get("tpm_enabled") and self.tpm_budget < self.cfg["max_tpm"]:
                self.tpm_budget = min(self.cfg["max_tpm"], self.tpm_budget + self.cfg["tpm_inc"])
                self.tpm_peak = max(self.tpm_peak, self.tpm_budget)
            # (2) concurrency (sekundárny strop)
            if not was_saturated:
                return
            self._sat_ok += 1
            if self._sat_ok >= self.cfg["probe_after"]:
                self._sat_ok = 0
                if self.limit < self.cfg["max_conc"]:
                    # sqrt headroom (Envoy/Netflix): rýchly rast keď malé, stabilný keď veľké
                    step = self.cfg["increase_step"] * (self.limit ** 0.5)
                    self.limit = min(self.cfg["max_conc"], self.limit + step)
                    self.limit_peak = max(self.limit_peak, self.limit)
                    self.cv.notify_all()

    def on_rate_limit(self, retry_after):
        """HTTP 429 = RATE limit signál (NIE concurrency!). v3: multiplikatívne zrezhe
        SENDING RATE (spomalí spacing), concurrency NEchytá — 429 pri conc=1 dokázal, že
        kolaps súbežnosti nič nerieši, len serializuje sessions do dlhej fronty."""
        with self.cv:
            self.rl_hits += 1
            self._sat_ok = 0
            # multiplicative decrease NA RATE (nie na concurrency)
            self.rate = max(self.cfg["min_rate"], self.rate * self.cfg["rate_dec"])
            self.rate_floor = min(self.rate_floor, self.rate)
            # a HLAVNE: multiplicative decrease na TPM budget (nauč sa reálny strop tokenov/min)
            if self.cfg.get("tpm_enabled"):
                self.tpm_budget = max(self.cfg["min_tpm"], self.tpm_budget * self.cfg["tpm_dec"])
                self.tpm_floor = min(self.tpm_floor, self.tpm_budget)
            # penalty okno: rešpektuj Retry-After ak dá, inak krátky base (spacing spraví zvyšok)
            base = retry_after if retry_after else self.cfg["penalty_base"]
            base = min(base, self.cfg["penalty_cap"])
            self._penalty_until = max(self._penalty_until, time.time() + base)
            # REAKTÍVNE rozostieranie: spacing sa aktivuje LEN v cooldown okne po 429.
            # Mimo neho (zdravý Palantir) gate prepúšťa okamžite = rovnako rýchlo ako bez gate.
            self._spacing_until = time.time() + self.cfg["spacing_cooldown"]
            return base

    def note_server_error(self, backoff):
        with self.cv:
            self.server_errs += 1
            delay = min(backoff, self.cfg["penalty_cap"])
            self._penalty_until = max(self._penalty_until, time.time() + delay)
            return delay

    # ── admission (dynamický concurrency) ─────────────────────────────────
    def acquire(self):
        """Pusti request len ak inflight < AIMD limit. Inak čaká (fronta), NEVRACIA error.
        Vráti was_saturated = či bol systém pri prijatí naozaj vyťažený (pre grow-only-busy).
        Saturácia = buď sme reálne čakali vo fronte (qwait), alebo inflight je blízko limitu."""
        q0 = time.time()
        with self.cv:
            while self.inflight >= max(1, int(self.limit)):
                self.cv.wait(timeout=1.0)
            self.inflight += 1
            infl = self.inflight
            lim = self.limit
        qwait = time.time() - q0
        with self.cv:
            self.max_queue_wait = max(self.max_queue_wait, qwait)
        was_saturated = (qwait > 0.05) or (infl >= lim * 0.8)
        return was_saturated

    def release(self):
        with self.cv:
            self.inflight -= 1
            self.cv.notify_all()

    def pace_before_start(self):
        """REAKTÍVNE rozostieranie (v3.2). Kľúč: gate NEbrzdí, keď je Palantir zdravý.
        - Ak sme v penalty okne (po 429/5xx) -> počkaj zvyšok + full jitter.
        - Ak sme v spacing-cooldown okne (nedávny 429) -> aplikuj adaptívny spacing 1/rate,
          aby sme dali Palantiru vydýchnuť.
        - INAK (žiadny nedávny 429) -> return OKAMŽITE, nulová pauza = rovnaká rýchlosť ako
          priame volanie bez gate. Toto rieši 's gate pomalšie než bez gate' pri 2+ sessions.
        _last_start sa aktualizuje vždy (aby spacing po prvom 429 mal referenciu)."""
        while True:
            with self.cv:
                now = time.time()
                if now < self._penalty_until:
                    remain = self._penalty_until - now
                    wait = remain + random.uniform(0.0, self.cfg["jitter_spread"])
                elif now < self._spacing_until:
                    # cooldown po 429: rozostieraj podľa naučeného rate
                    interval = 1.0 / max(self.rate, 0.01)
                    if now - self._last_start < interval:
                        wait = interval - (now - self._last_start)
                    else:
                        self._last_start = now
                        return
                else:
                    # zdravý Palantir -> žiadne brzdenie, prepusti hneď
                    self._last_start = now
                    return
            time.sleep(wait)

    # ── ADAPTÍVNY TPM sliding-window (v3.1) ───────────────────────────────
    def _prune_tpm_locked(self):
        cutoff = time.time() - 60.0
        while self._tpm_window and self._tpm_window[0][0] < cutoff:
            _, tk = self._tpm_window.pop(0)
            self._tpm_used -= tk
        if self._tpm_used < 0:
            self._tpm_used = 0.0

    def await_tpm_budget(self, est_tokens):
        """Blokuj, kým sa v 60s okne uvoľní miesto pre est_tokens proti tpm_budget.
        Toto je HLAVNÁ brzda: veľký request (veľa tokenov) počká dlhšie, malý prejde hneď.
        Vracia čakací čas (pre metriku).

        POZOR: default VYPNUTÉ (cfg['tpm_enabled']=False). Dôvod (dôkaz 2026-09-28): jeden
        reálny Hermes session request má ~110k odhadovaných tokenov — viac než rozumný
        60s budget. Sliding-window by taký request nechal zaplniť okno a KAŽDÝ ďalší by
        čakal 60s => serializácia, HORŠIE než bez brzdy. TPM-aware pacing dáva zmysel len
        pre veľa MALÝCH requestov (napr. embeddingy/batch), nie pre veľko-kontextové chaty.
        Zapni len cielene cez --tpm-enabled na taký workload."""
        if not self.cfg.get("tpm_enabled"):
            return 0.0
        t0 = time.time()
        while True:
            with self.cv:
                self._prune_tpm_locked()
                # ak by aj sám request bol väčší než budget, pusti ho (inak deadlock)
                if self._tpm_used + est_tokens <= self.tpm_budget or est_tokens >= self.tpm_budget:
                    self._tpm_window.append((time.time(), est_tokens))
                    self._tpm_used += est_tokens
                    waited = time.time() - t0
                    self.max_queue_wait = max(self.max_queue_wait, waited)
                    return waited
                # spočítaj, kedy najstarší kus vypadne z okna -> vtedy skús znova
                oldest_ts = self._tpm_window[0][0] if self._tpm_window else time.time()
                sleep_for = max(0.05, min(2.0, (oldest_ts + 60.0) - time.time()))
            time.sleep(sleep_for)

    def stats(self):
        with self.cv:
            self._refill_locked()
            now = time.time()
            return {
                "limit": round(self.limit, 2),
                "inflight": self.inflight,
                "rate_rps": round(self.rate, 3),
                "interval_s": round(1.0 / max(self.rate, 0.01), 3),
                "rate_peak": round(self.rate_peak, 3),
                "rate_floor": round(self.rate_floor, 3),
                "tpm_budget": round(self.tpm_budget, 0),
                "tpm_used_60s": round(self._tpm_used, 0),
                "tpm_peak": round(self.tpm_peak, 0),
                "tpm_floor": round(self.tpm_floor, 0),
                "limit_peak": round(self.limit_peak, 2),
                "limit_floor": round(self.limit_floor, 2),
                "total_requests": self.total,
                "forbidden_403": self.forbidden,
                "rate_limit_hits": self.rl_hits,
                "server_errors": self.server_errs,
                "transparent_retries": self.retries,
                "retries_denied": self.retries_denied,
                "retry_tokens": round(self.retry_tokens, 1),
                "max_queue_wait_s": round(self.max_queue_wait, 2),
                "penalty_active_s": round(max(0.0, self._penalty_until - now), 2),
            }


class Registry:
    """Router per-model gate-ov + zdieľaný token pool (multi-account) + globálne knoby."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.gates = {}
        self.lock = threading.Lock()
        self.tokens = self._load_tokens()
        self._tok_i = 0
        self.started = time.time()

    def _load_tokens(self):
        raw = os.environ.get("GATE_TOKENS", "").strip()
        toks = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
        if not toks:
            p = os.path.expanduser("~/.hermes/palantir_tokens.txt")
            if os.path.exists(p):
                for line in open(p, encoding="utf-8"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        toks.append(line)
        return toks

    def next_token(self):
        if not self.tokens:
            return None
        with self.lock:
            t = self.tokens[self._tok_i % len(self.tokens)]
            self._tok_i += 1
            return t

    def gate_for(self, model_key):
        with self.lock:
            g = self.gates.get(model_key)
            if g is None:
                g = ModelGate(model_key, self.cfg)
                self.gates[model_key] = g
            return g

    def stats(self):
        with self.lock:
            per_model = {k: g.stats() for k, g in self.gates.items()}
        return {
            "uptime_s": round(time.time() - self.started, 1),
            "version": "v3-adaptive-rate",
            "config": {k: self.cfg[k] for k in
                       ("min_conc", "max_conc", "initial_conc", "decrease_factor",
                        "increase_step", "probe_after", "jitter_spread",
                        "initial_rate", "min_rate", "max_rate", "rate_inc", "rate_dec",
                        "initial_tpm", "min_tpm", "max_tpm", "tpm_inc", "tpm_dec",
                        "retry_bucket_max", "retry_refill_per_s")},
            "token_pool_size": len(self.tokens),
            "mode": "multi-token round-robin" if self.tokens else "single-token passthrough",
            "models": per_model,
        }


REG = None


def _log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _model_key(path, body):
    """Per-model kľúč: najprv 'model' z JSON tela (presné per-model podľa Palantiru),
    fallback prefix cesty (provider family)."""
    if body:
        try:
            j = json.loads(body)
            m = j.get("model")
            if isinstance(m, str) and m:
                return m
        except (ValueError, AttributeError):
            pass
    p = path.lstrip("/")
    for fam in ("anthropic", "openai", "google"):
        if p.startswith(fam):
            return f"_{fam}"
    return "_default"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _stats_reply(self):
        body = json.dumps(REG.stats(), indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        if self.path.startswith("/_gate/stats"):
            self._stats_reply()
            return

        clen = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(clen) if clen else b""

        up_headers = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in _HOP or lk in ("host", "content-length"):
                continue
            up_headers[k] = v

        _has_auth = any(h.lower() in ("authorization", "x-api-key", "api-key")
                        for h in self.headers.keys())
        model_key = _model_key(self.path, body)
        _log(f"REQ {self.command} {self.path} model={model_key} auth_present={_has_auth}")

        tok = REG.next_token()
        if tok:
            up_headers["Authorization"] = f"Bearer {tok}"
        else:
            if "Authorization" not in up_headers and "authorization" not in up_headers:
                api_key = None
                for k in list(up_headers.keys()):
                    if k.lower() in ("x-api-key", "api-key"):
                        api_key = up_headers.pop(k)
                if api_key:
                    up_headers["Authorization"] = f"Bearer {api_key}"
        up_headers["Host"] = UPSTREAM_HOST
        up_path = UPSTREAM_BASE + self.path

        gate = REG.gate_for(model_key)
        with gate.cv:
            gate.total += 1
        # TPM rezervácia (v3.1 HLAVNÁ brzda): odhad tokenov ≈ dĺžka tela / 4 (heuristika bez
        # tokenizéra, shell-safe). Veľký request počká, kým sa uvoľní 60s TPM okno; malý prejde.
        est_tokens = max(1, len(body) // 4)
        tpm_wait = gate.await_tpm_budget(est_tokens)
        was_saturated = gate.acquire()
        if tpm_wait > 0.05:
            _log(f"[{gate.name}] TPM-WAIT {tpm_wait:.2f}s est_tok={est_tokens} budget={gate.tpm_budget:.0f}")
        try:
            self._proxy_with_retry(gate, up_path, up_headers, body, was_saturated)
        finally:
            gate.release()

    def _proxy_with_retry(self, gate, up_path, up_headers, body, was_saturated):
        attempt = 0
        while True:
            gate.pace_before_start()
            try:
                if _TEST_UPSTREAM:
                    conn = http.client.HTTPConnection(
                        UPSTREAM_HOST, UPSTREAM_PORT, timeout=600)
                else:
                    conn = http.client.HTTPSConnection(
                        UPSTREAM_HOST, UPSTREAM_PORT, context=_CTX, timeout=600)
                conn.request(self.command, up_path, body=body, headers=up_headers)
                resp = conn.getresponse()
            except Exception as e:
                # sieťová chyba: retry len ak je retry token (inak prepusti)
                if gate.try_take_retry_token():
                    attempt += 1
                    with gate.cv:
                        gate.retries += 1
                    base = min(2 ** attempt, gate.cfg["penalty_cap"])
                    gate.note_server_error(base)
                    delay = random.uniform(0.0, base)   # full jitter
                    _log(f"[{gate.name}] NET-ERR {e!r} attempt={attempt} jitter_backoff={delay:.2f}s")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    time.sleep(delay)
                    continue
                self._fail(502, f"gate upstream error (retry budget vycerpany): {e!r}")
                return

            status = resp.status

            if status in _RATE_STATUS and gate.try_take_retry_token():
                ra = resp.getheader("Retry-After")
                try:
                    ra_s = float(ra) if ra else 0.0
                except ValueError:
                    ra_s = 0.0
                resp.read(); conn.close()
                attempt += 1
                with gate.cv:
                    gate.retries += 1
                base = gate.on_rate_limit(ra_s)
                delay = random.uniform(0.0, base)       # full jitter na 429
                _log(f"[{gate.name}] 429 attempt={attempt} new_rate={gate.rate:.2f}rps jitter_backoff={delay:.2f}s")
                time.sleep(delay)
                continue

            if status in _SERVER_STATUS and gate.try_take_retry_token():
                resp.read(); conn.close()
                attempt += 1
                with gate.cv:
                    gate.retries += 1
                base = gate.note_server_error(min(2 ** attempt, gate.cfg["penalty_cap"]))
                delay = random.uniform(0.0, base)
                _log(f"[{gate.name}] {status} attempt={attempt} jitter_backoff={delay:.2f}s")
                time.sleep(delay)
                continue

            if status == 403:
                # Filter:RequestBlocked = egress IP nie je na Palantir allowliste (retryable:false).
                # NIE je to rate/concurrency — gate to NEretryuje, len zaloguje sourceIp z tela
                # (telo si samo nesie diagnostiku) a prepustí ku klientovi nezmenené.
                raw = resp.read(); conn.close()
                src_ip = err_code = err_id = "?"
                try:
                    j = json.loads(raw)
                    err_code = j.get("errorCode") or j.get("errorName") or "?"
                    err_id = j.get("errorInstanceId", "?")
                    src_ip = (j.get("parameters") or {}).get("sourceIp", "?")
                except (ValueError, AttributeError):
                    pass
                with gate.cv:
                    gate.forbidden = getattr(gate, "forbidden", 0) + 1
                _log(f"[{gate.name}] 403 BLOCKED code={err_code} sourceIp={src_ip} "
                     f"instid={err_id} forbidden_total={gate.forbidden}")
                self._relay_prebuffered(resp, raw)
                return

            if status == 200:
                gate.on_success(was_saturated)
            self._relay(resp, conn)
            return

    def _relay_prebuffered(self, resp, body_bytes):
        """Relay odpovede, ktorej telo sme UŽ prečítali (napr. 403 kde peekujeme sourceIp).
        Headers ostávajú platné aj po resp.read()."""
        try:
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk in _HOP or lk == "content-length":
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _relay(self, resp, conn):
        try:
            self.send_response(resp.status)
            clen = resp.getheader("Content-Length")
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk in _HOP or lk == "content-length":
                    continue
                self.send_header(k, v)
            if clen is not None:
                self.send_header("Content-Length", clen)
            else:
                self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            if clen is not None:
                remaining = int(clen)
                while remaining > 0:
                    chunk = resp.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            else:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(b"%X\r\n" % len(chunk))
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _fail(self, code, msg):
        try:
            body = json.dumps({"error": {"type": "gate_error", "message": msg}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()


def build_cfg(args):
    return {
        "min_conc": args.min_conc,
        "max_conc": args.max_conc,
        "initial_conc": args.initial_conc,
        "increase_step": args.increase_step,
        "decrease_factor": args.decrease_factor,
        "probe_after": args.probe_after,
        "min_interval": args.min_interval,
        # ── adaptívny rate (v3) ──
        "initial_rate": args.initial_rate,
        "min_rate": args.min_rate,
        "max_rate": args.max_rate,
        "rate_inc": args.rate_inc,
        "rate_dec": args.rate_dec,
        # ── adaptívny TPM budget (v3.1) ──
        "tpm_enabled": args.tpm_enabled,
        "initial_tpm": args.initial_tpm,
        "min_tpm": args.min_tpm,
        "max_tpm": args.max_tpm,
        "tpm_inc": args.tpm_inc,
        "tpm_dec": args.tpm_dec,
        "penalty_base": args.penalty_base,
        "penalty_cap": args.penalty_cap,
        "spacing_cooldown": args.spacing_cooldown,
        "jitter_spread": args.jitter_spread,
        "retry_bucket_max": args.retry_bucket_max,
        "retry_refill_per_s": args.retry_refill_per_s,
        "retry_success_credit": args.retry_success_credit,
    }


def main():
    global REG
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("GATE_PORT", 8787)))
    ap.add_argument("--min-conc", type=float, default=float(os.environ.get("GATE_MIN_CONC", 1)))
    ap.add_argument("--max-conc", type=float, default=float(os.environ.get("GATE_MAX_CONC", 8)))
    ap.add_argument("--initial-conc", type=float, default=float(os.environ.get("GATE_INIT_CONC", 3)))
    ap.add_argument("--increase-step", type=float, default=float(os.environ.get("GATE_INC_STEP", 0.25)))
    ap.add_argument("--decrease-factor", type=float, default=float(os.environ.get("GATE_DEC_FACTOR", 0.5)))
    ap.add_argument("--probe-after", type=int, default=int(os.environ.get("GATE_PROBE_AFTER", 8)))
    ap.add_argument("--min-interval", type=float, default=float(os.environ.get("GATE_MIN_INTERVAL", 0.3)))
    # ── adaptívny sending rate (v3) ── default: štart 3 rps, strop 8 rps, dno 0.25 rps
    ap.add_argument("--initial-rate", type=float, default=float(os.environ.get("GATE_INIT_RATE", 3.0)))
    ap.add_argument("--min-rate", type=float, default=float(os.environ.get("GATE_MIN_RATE", 0.25)))
    ap.add_argument("--max-rate", type=float, default=float(os.environ.get("GATE_MAX_RATE", 8.0)))
    ap.add_argument("--rate-inc", type=float, default=float(os.environ.get("GATE_RATE_INC", 0.25)))
    ap.add_argument("--rate-dec", type=float, default=float(os.environ.get("GATE_RATE_DEC", 0.5)))
    # ── adaptívny TPM budget (v3.1) ── DEFAULT VYPNUTÉ (viď await_tpm_budget docstring)
    ap.add_argument("--tpm-enabled", action="store_true",
                    default=(os.environ.get("GATE_TPM_ENABLED", "0") == "1"))
    ap.add_argument("--initial-tpm", type=float, default=float(os.environ.get("GATE_INIT_TPM", 40000)))
    ap.add_argument("--min-tpm", type=float, default=float(os.environ.get("GATE_MIN_TPM", 8000)))
    ap.add_argument("--max-tpm", type=float, default=float(os.environ.get("GATE_MAX_TPM", 120000)))
    ap.add_argument("--tpm-inc", type=float, default=float(os.environ.get("GATE_TPM_INC", 2000)))
    ap.add_argument("--tpm-dec", type=float, default=float(os.environ.get("GATE_TPM_DEC", 0.7)))
    ap.add_argument("--penalty-base", type=float, default=float(os.environ.get("GATE_PENALTY_BASE", 0.5)))
    ap.add_argument("--penalty-cap", type=float, default=float(os.environ.get("GATE_PENALTY_CAP", 30.0)))
    # v3.2 reaktívne spacing: koľko sekúnd po 429 gate rozostiera; mimo okna prepúšťa OKAMŽITE
    ap.add_argument("--spacing-cooldown", type=float, default=float(os.environ.get("GATE_SPACING_COOLDOWN", 10.0)))
    ap.add_argument("--jitter-spread", type=float, default=float(os.environ.get("GATE_JITTER_SPREAD", 1.5)))
    ap.add_argument("--retry-bucket-max", type=float, default=float(os.environ.get("GATE_RETRY_BUCKET", 20.0)))
    ap.add_argument("--retry-refill-per-s", type=float, default=float(os.environ.get("GATE_RETRY_REFILL", 0.5)))
    ap.add_argument("--retry-success-credit", type=float, default=float(os.environ.get("GATE_RETRY_CREDIT", 1.0)))
    args = ap.parse_args()

    REG = Registry(build_cfg(args))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.request_queue_size = 128
    srv.daemon_threads = True
    _log(f"START-V3 port={args.port} init_rate={args.initial_rate}rps "
         f"rate_bounds=[{args.min_rate},{args.max_rate}] conc=[{args.min_conc},{args.max_conc}] tokens={len(REG.tokens)}")
    print(f"[palantir-gate-v3] listening 127.0.0.1:{args.port} per-model adaptive TPM+RATE "
          f"init_tpm={args.initial_tpm:.0f} tpm_bounds=[{args.min_tpm:.0f},{args.max_tpm:.0f}] "
          f"init_rate={args.initial_rate}rps conc=[{args.min_conc},{args.max_conc}] "
          f"({REG.stats()['mode']})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
