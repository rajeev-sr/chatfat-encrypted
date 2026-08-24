// Command lb is the round-robin reverse-proxy load balancer that runs on Sys1.
//
// Topology for the assignment:
//
//	Load Generator (laptop) --> LB (Sys1) --> ChatFat backends on Sys2/Sys3/Sys4
//
// The backends are the messaging project itself, so the health path defaults to
// /healthz (what ChatFat exposes) rather than the /health of a toy backend, and
// the proxy is left able to carry WebSocket upgrades: net/http/httputil has
// handled 101 responses natively since Go 1.20, and the chat app is useless
// through a proxy that cannot.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// Backend is one upstream server. Every mutable field is atomic because a
// request goroutine, the health loop and the metrics handler all touch them
// concurrently.
type Backend struct {
	URL      *url.URL
	Alive    atomic.Bool
	InFlight atomic.Int64

	Requests atomic.Uint64 // requests dispatched here
	Errors   atomic.Uint64 // proxy failures charged to this backend

	// Consecutive probe outcomes, for the eviction/restoration hysteresis
	// below. Only the health loop writes these, and only from one goroutine
	// per backend, so plain ints under the health loop's ownership would do —
	// atomics keep /lb/status able to report them.
	failStreak atomic.Int64
	okStreak   atomic.Int64

	proxy *httputil.ReverseProxy
}

func (b *Backend) Name() string { return b.URL.Host }

// Metrics are the load balancer's own counters, reported by /lb/metrics.
type Metrics struct {
	Total          atomic.Uint64
	Success        atomic.Uint64
	Failed         atomic.Uint64
	BackendErrors  atomic.Uint64
	NoBackend      atomic.Uint64 // rejected because every backend was down
	ClientCanceled atomic.Uint64 // client gave up before the backend answered
	TLSHandshakes  atomic.Uint64 // inbound connections that died before the TLS handshake finished

	latencyMu      sync.Mutex
	latencies      []time.Duration
	latencyDropped uint64
}

// maxLatencySamples bounds the latency slice. Percentiles need the individual
// samples, so this grows with request count — unbounded, a load balancer left
// in front of the chat app for a day accumulates memory for no reason. The cap
// is far above any experiment here (5000 requests per run); past it, samples
// are dropped rather than replaced, so the reported percentiles describe the
// first maxLatencySamples requests of the window and `samples` in /lb/metrics
// says how many that was.
const maxLatencySamples = 1 << 20

func (m *Metrics) observe(d time.Duration) {
	m.latencyMu.Lock()
	if len(m.latencies) < maxLatencySamples {
		m.latencies = append(m.latencies, d)
	} else {
		m.latencyDropped++
	}
	m.latencyMu.Unlock()
}

// snapshotLatencies returns a sorted copy, so percentiles can be computed
// without holding the mutex across the arithmetic.
func (m *Metrics) snapshotLatencies() []time.Duration {
	m.latencyMu.Lock()
	out := make([]time.Duration, len(m.latencies))
	copy(out, m.latencies)
	m.latencyMu.Unlock()
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

func (m *Metrics) droppedLatencies() uint64 {
	m.latencyMu.Lock()
	defer m.latencyMu.Unlock()
	return m.latencyDropped
}

func (m *Metrics) reset() {
	m.Total.Store(0)
	m.Success.Store(0)
	m.Failed.Store(0)
	m.BackendErrors.Store(0)
	m.NoBackend.Store(0)
	m.ClientCanceled.Store(0)
	m.TLSHandshakes.Store(0)
	m.latencyMu.Lock()
	m.latencies = m.latencies[:0]
	m.latencyDropped = 0
	m.latencyMu.Unlock()
}

// percentile takes a pre-sorted slice. p is 0..100.
func percentile(sorted []time.Duration, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	// nearest-rank: the same rule the load generator uses, so LB-side and
	// client-side numbers in the report are comparable.
	idx := int(p / 100 * float64(len(sorted)))
	if idx >= len(sorted) {
		idx = len(sorted) - 1
	}
	if idx < 0 {
		idx = 0
	}
	return float64(sorted[idx].Microseconds()) / 1000
}

type LoadBalancer struct {
	backends []*Backend
	next     atomic.Uint64
	metrics  Metrics
	// Unix nanoseconds rather than a time.Time, because /lb/reset restarts the
	// measurement window while the metrics handlers are reading it. A time.Time
	// is a multi-word struct, so that is a genuine torn-read race (the detector
	// flags it); an atomic int64 makes the reset publish a single value.
	startedNanos atomic.Int64
}

// backendTLS is the TLS configuration used for every outbound connection to a
// backend — the proxy's and the health probe's alike. They must agree: a health
// loop that trusts the certificate while the proxy does not (or the reverse)
// reports a backend as healthy and then fails every request to it.
func backendTLS() *tls.Config {
	if !insecureBackends {
		return nil // system trust store
	}
	return &tls.Config{InsecureSkipVerify: true} // #nosec G402 — see insecureBackends
}

func (lb *LoadBalancer) markStart() { lb.startedNanos.Store(time.Now().UnixNano()) }

// uptime is the length of the current measurement window: since process start,
// or since the last /lb/reset.
func (lb *LoadBalancer) uptime() time.Duration {
	return time.Since(time.Unix(0, lb.startedNanos.Load()))
}

// nextBackend advances the round-robin cursor and returns the first healthy
// backend it lands on. One full pass; nil means everything is down.
func (lb *LoadBalancer) nextBackend() *Backend {
	n := uint64(len(lb.backends))
	if n == 0 {
		return nil
	}
	for i := uint64(0); i < n; i++ {
		idx := lb.next.Add(1) % n
		if b := lb.backends[idx]; b.Alive.Load() {
			return b
		}
	}
	return nil
}

func (lb *LoadBalancer) healthLoop(ctx context.Context, path string, interval, timeout time.Duration) {
	// Its own client, and deliberately not the proxy transport: probes must not
	// queue behind the request traffic they are trying to measure. Its TLS
	// settings still have to match the proxy's — see backendTLS.
	client := &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			TLSClientConfig:     backendTLS(),
			TLSHandshakeTimeout: 5 * time.Second,
			DisableKeepAlives:   false,
		},
	}

	// record applies hysteresis. A single missed probe does not evict, because
	// the backends here are single-threaded Node processes: at saturation the
	// probe queues behind the request backlog and times out while the server is
	// perfectly alive. Evicting on that one sample removes the last healthy
	// backend, every request is then refused instantly, the offered load
	// vanishes, the next probe succeeds, and the backend is restored — a
	// flap loop that reports the load balancer's own oscillation as backend
	// failure. Requiring -unhealthy-threshold consecutive failures distinguishes
	// "busy" from "gone"; restoration is faster than eviction on purpose, so
	// recovery is not delayed by the same margin that prevents flapping.
	record := func(b *Backend, ok bool, detail string) {
		if ok {
			b.failStreak.Store(0)
			if n := b.okStreak.Add(1); n >= int64(healthyThreshold) && !b.Alive.Load() {
				b.Alive.Store(true)
				log.Printf("health: %s UP after %d good probes (%s)", b.Name(), n, detail)
			}
			return
		}
		b.okStreak.Store(0)
		if n := b.failStreak.Add(1); n >= int64(unhealthyThreshold) && b.Alive.Load() {
			b.Alive.Store(false)
			log.Printf("health: %s DOWN after %d failed probes (%s)", b.Name(), n, detail)
		}
	}

	check := func(b *Backend) {
		target := strings.TrimRight(b.URL.String(), "/") + path
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
		if err != nil {
			record(b, false, err.Error())
			return
		}
		resp, err := client.Do(req)
		if err != nil {
			record(b, false, err.Error())
			return
		}
		// Drained and closed, so the probe connection is reusable; a leaked
		// probe body per second is a slow file-descriptor leak.
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))
		resp.Body.Close()
		ok := resp.StatusCode >= 200 && resp.StatusCode < 400
		record(b, ok, fmt.Sprintf("status %d", resp.StatusCode))
	}

	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		var wg sync.WaitGroup
		for _, b := range lb.backends {
			wg.Add(1)
			// Probed in parallel: serial probing makes the effective interval
			// scale with the number of dead backends, so one hung machine
			// would delay the health news about all the others.
			go func(b *Backend) { defer wg.Done(); check(b) }(b)
		}
		wg.Wait()
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

// ServeHTTP is the data path: pick a backend, proxy, record.
func (lb *LoadBalancer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	lb.metrics.Total.Add(1)
	start := time.Now()

	b := lb.nextBackend()
	if b == nil {
		lb.metrics.Failed.Add(1)
		lb.metrics.NoBackend.Add(1)
		lb.metrics.observe(time.Since(start))
		http.Error(w, "no healthy backend", http.StatusServiceUnavailable)
		return
	}

	b.Requests.Add(1)
	b.InFlight.Add(1)
	defer b.InFlight.Add(-1)

	// The proxy's own ErrorHandler counts the failures, so anything that
	// reaches here without having been counted succeeded.
	rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
	r.Header.Set("X-Forwarded-Host", r.Host)
	r.Header.Set("X-LB-Backend", b.Name())
	b.proxy.ServeHTTP(rec, r)

	d := time.Since(start)
	lb.metrics.observe(d)
	if rec.failed {
		return // already charged to Failed by ErrorHandler
	}
	if rec.status >= 500 {
		lb.metrics.Failed.Add(1)
		return
	}
	lb.metrics.Success.Add(1)
}

// statusRecorder remembers the status line so the LB can tell a 200 from a 502
// without buffering the body.
type statusRecorder struct {
	http.ResponseWriter
	status int
	wrote  bool
	failed bool
}

func (s *statusRecorder) WriteHeader(code int) {
	if s.wrote {
		return
	}
	s.status = code
	s.wrote = true
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(p []byte) (int, error) {
	if !s.wrote {
		s.wrote = true
	}
	return s.ResponseWriter.Write(p)
}

// Hijack keeps WebSocket upgrades working through the recorder — without it
// the proxy cannot take over the connection and every /ws handshake fails.
func (s *statusRecorder) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	h, ok := s.ResponseWriter.(http.Hijacker)
	if !ok {
		return nil, nil, fmt.Errorf("lb: ResponseWriter is not a Hijacker")
	}
	return h.Hijack()
}

func (s *statusRecorder) Flush() {
	if f, ok := s.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (lb *LoadBalancer) handleStatus(w http.ResponseWriter, _ *http.Request) {
	type row struct {
		URL          string `json:"url"`
		Alive        bool   `json:"alive"`
		InFlight     int64  `json:"in_flight"`
		Requests     uint64 `json:"requests"`
		Errors       uint64 `json:"errors"`
		FailedProbes int64  `json:"consecutive_failed_probes"`
	}
	out := struct {
		Backends []row   `json:"backends"`
		Healthy  int     `json:"healthy"`
		UptimeS  float64 `json:"uptime_s"`
	}{UptimeS: lb.uptime().Seconds()}
	for _, b := range lb.backends {
		alive := b.Alive.Load()
		if alive {
			out.Healthy++
		}
		out.Backends = append(out.Backends, row{b.URL.String(), alive, b.InFlight.Load(), b.Requests.Load(), b.Errors.Load(), b.failStreak.Load()})
	}
	writeJSON(w, http.StatusOK, out)
}

func (lb *LoadBalancer) handleMetrics(w http.ResponseWriter, _ *http.Request) {
	lat := lb.metrics.snapshotLatencies()
	total := lb.metrics.Total.Load()
	failed := lb.metrics.Failed.Load()
	elapsed := lb.uptime().Seconds()

	dropout := 0.0
	if total > 0 {
		dropout = float64(failed) / float64(total) * 100
	}
	rps := 0.0
	if elapsed > 0 {
		rps = float64(lb.metrics.Success.Load()) / elapsed
	}

	per := map[string]uint64{}
	for _, b := range lb.backends {
		per[b.Name()] = b.Requests.Load()
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"total":                  total,
		"success":                lb.metrics.Success.Load(),
		"failed":                 failed,
		"backend_errors":         lb.metrics.BackendErrors.Load(),
		"no_backend":             lb.metrics.NoBackend.Load(),
		"client_canceled":        lb.metrics.ClientCanceled.Load(),
		"tls_handshake_failures": lb.metrics.TLSHandshakes.Load(),
		"dropout_percent":        round2(dropout),
		"uptime_s":               round2(elapsed),
		"throughput_rps":         round2(rps),
		"p50_ms":                 round2(percentile(lat, 50)),
		"p95_ms":                 round2(percentile(lat, 95)),
		"p99_ms":                 round2(percentile(lat, 99)),
		"samples":                len(lat),
		"samples_dropped":        lb.metrics.droppedLatencies(),
		"per_backend_reqs":       per,
	})
}

// serverErrorLog filters net/http's connection-level error log.
//
// "TLS handshake error ... EOF" means a client opened a TCP connection and went
// away before completing the handshake. That is a client-side event, and under
// load it arrives once per abandoned connection — hundreds of lines that bury
// every message that matters, which is exactly when the operator most needs to
// read the log. Counted instead, and surfaced in /lb/metrics as
// tls_handshake_failures; everything else passes through unchanged.
type serverErrorLog struct {
	out   io.Writer
	count *atomic.Uint64
}

func (s serverErrorLog) Write(p []byte) (int, error) {
	if bytes.Contains(p, []byte("TLS handshake error")) {
		s.count.Add(1)
		return len(p), nil
	}
	return s.out.Write(p)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("content-type", "application/json; charset=utf-8")
	w.Header().Set("cache-control", "no-store")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}

func round2(f float64) float64 { return float64(int64(f*100+0.5)) / 100 }

// insecureBackends turns off certificate verification for backend connections.
//
// It exists because the backends here present a self-signed certificate, which
// nothing trusts by default. Worth being clear about what this costs: skipping
// verification keeps the encryption and gives up the authentication, so the
// connection is protected against passive eavesdropping but not against a
// man-in-the-middle that can answer at the backend's address. On a lab bridge
// that is an acceptable trade; on a real network it is not, and the fix there
// is a certificate the load balancer actually trusts, not this flag.
var insecureBackends bool

// unhealthyThreshold / healthyThreshold are the health-check hysteresis; see
// the comment on record() in healthLoop.
var (
	unhealthyThreshold = 3
	healthyThreshold   = 1
)

// strictEviction reproduces the literal evict-on-any-proxy-error rule from the
// assignment slides. Off by default — see the ErrorHandler comment.
var strictEviction bool

// isTimeout reports whether err is a deadline/timeout rather than a refused or
// broken connection. net.Error.Timeout covers the transport's own
// ResponseHeaderTimeout and dial deadlines; context.DeadlineExceeded covers a
// cancelled request context.
func isTimeout(err error) bool {
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded) {
		return true
	}
	var ne net.Error
	if errors.As(err, &ne) {
		return ne.Timeout()
	}
	return false
}

func parseBackends(raw string, timeout time.Duration, lb *LoadBalancer) ([]*Backend, error) {
	var out []*Backend
	// Split on commas AND whitespace, so a -backends value pasted across
	// several shell lines (as the slides show it) still parses.
	for _, part := range strings.FieldsFunc(raw, func(r rune) bool {
		return r == ',' || r == ' ' || r == '\t' || r == '\n'
	}) {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if !strings.Contains(part, "://") {
			part = "http://" + part
		}
		u, err := url.Parse(part)
		if err != nil {
			return nil, fmt.Errorf("bad backend %q: %w", part, err)
		}
		if u.Host == "" {
			return nil, fmt.Errorf("bad backend %q: no host", part)
		}
		b := &Backend{URL: u}
		// Optimistic start: the first health tick corrects it within a second,
		// and starting pessimistic means the very first requests 503 even
		// when every backend is fine.
		b.Alive.Store(true)

		p := httputil.NewSingleHostReverseProxy(u)
		p.Transport = &http.Transport{
			DialContext:           (&net.Dialer{Timeout: 2 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
			ResponseHeaderTimeout: timeout,
			// Generous, and per-host: the default of 2 idle connections per
			// host turns a 40-way concurrent test into connection churn and
			// measures the TCP handshake instead of the backend.
			MaxIdleConns:        512,
			MaxIdleConnsPerHost: 256,
			IdleConnTimeout:     90 * time.Second,
			ForceAttemptHTTP2:   false,
			TLSClientConfig:     backendTLS(),
			TLSHandshakeTimeout: 5 * time.Second,
		}
		p.ErrorHandler = func(rw http.ResponseWriter, req *http.Request, err error) {
			// The client hung up: its deadline expired, it was interrupted, or
			// the connection dropped. The backend is not at fault and must not
			// be evicted for it. Getting this wrong is self-reinforcing under
			// load — a client-side deadline abandons requests exactly when the
			// backend is slowest, so every abandoned request would evict the
			// one backend still doing the work, and the load balancer would
			// refuse traffic it could have served.
			//
			// Counted as failed, because the request was not served, but kept
			// separate from BackendErrors so the report can tell "the client
			// gave up" apart from "the backend broke". Not logged either: under
			// a short client deadline these arrive in the thousands, and a log
			// that scrolls is a log nobody reads.
			if req.Context().Err() != nil || errors.Is(err, context.Canceled) {
				lb.metrics.ClientCanceled.Add(1)
				lb.metrics.Failed.Add(1)
				if rec, ok := rw.(*statusRecorder); ok {
					rec.failed = true
				}
				return // the connection is gone; there is nobody to write to
			}

			b.Errors.Add(1)
			lb.metrics.BackendErrors.Add(1)
			lb.metrics.Failed.Add(1)
			if rec, ok := rw.(*statusRecorder); ok {
				rec.failed = true
			}

			// A slow backend and a dead backend are different faults, and
			// treating them alike is a self-inflicted outage: the moment an
			// overloaded backend misses the response-header deadline, evicting
			// it leaves nothing in rotation, so every subsequent request is
			// refused instantly. With one backend configured that turns a
			// throughput measurement into a 100%-dropout cliff — the load
			// balancer, not the backend, becomes the thing that failed.
			//
			// So only connection-level faults evict. A timeout is reported as
			// 504 and the backend stays in rotation; if it is genuinely gone,
			// the health loop notices within one interval and evicts it there.
			// -strict-eviction restores the evict-on-any-error behaviour.
			timeout := isTimeout(err)
			if strictEviction || !timeout {
				// okStreak too: it is the "consecutive good probes" counter the
				// health loop restores on, and leaving it running across an
				// eviction produced the nonsensical "UP after 32 good probes"
				// immediately after a backend was marked down.
				b.okStreak.Store(0)
				b.Alive.Store(false)
			}
			status := http.StatusBadGateway
			if timeout {
				status = http.StatusGatewayTimeout
			}
			log.Printf("proxy error via %s (%s): %v", b.Name(), http.StatusText(status), err)
			http.Error(rw, http.StatusText(status), status)
		}
		b.proxy = p
		out = append(out, b)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("no backends given")
	}
	return out, nil
}

func main() {
	// Required, with no default. The assigned port differs per student and per
	// system, and a default that silently binds the wrong one produces a load
	// balancer that is running and unreachable — the most expensive kind of
	// wrong. Stating it is cheaper than diagnosing it.
	listen := flag.String("listen", "", "address to listen on, e.g. 0.0.0.0:3273 (required)")
	backends := flag.String("backends", "", "comma-separated backend URLs, e.g. http://10.1.75.53:3274,http://10.1.75.53:3275")
	healthPath := flag.String("health-path", "/healthz", "path probed on each backend (ChatFat exposes /healthz)")
	healthInterval := flag.Duration("health-interval", time.Second, "how often to probe backends")
	healthTimeout := flag.Duration("health-timeout", 800*time.Millisecond, "per-probe timeout")
	backendTimeout := flag.Duration("backend-timeout", 5*time.Second, "backend response-header timeout")
	tlsCert := flag.String("tls-cert", "", "PEM certificate; with -tls-key, the load balancer itself serves HTTPS")
	tlsKey := flag.String("tls-key", "", "PEM private key for -tls-cert")
	flag.BoolVar(&insecureBackends, "insecure-backends", false,
		"skip certificate verification when connecting to https:// backends (needed for self-signed certs)")
	flag.IntVar(&unhealthyThreshold, "unhealthy-threshold", 3, "consecutive failed probes before a backend is evicted")
	flag.IntVar(&healthyThreshold, "healthy-threshold", 1, "consecutive good probes before an evicted backend returns")
	flag.BoolVar(&strictEviction, "strict-eviction", false,
		"evict a backend on ANY proxy error, timeouts included (the slides' literal rule; collapses under overload)")
	flag.Parse()

	if *listen == "" || *backends == "" {
		if *listen == "" {
			fmt.Fprintln(os.Stderr, "lb: -listen is required, e.g. -listen 0.0.0.0:3273")
		}
		if *backends == "" {
			fmt.Fprintln(os.Stderr, "lb: -backends is required, e.g. -backends http://10.1.75.53:3274")
		}
		flag.Usage()
		os.Exit(2)
	}

	if (*tlsCert == "") != (*tlsKey == "") {
		fmt.Fprintln(os.Stderr, "lb: -tls-cert and -tls-key must be given together")
		os.Exit(2)
	}
	// The single most likely way to get this wrong is to point https:// backends
	// at a self-signed certificate and leave verification on, which fails every
	// probe with an unhelpful x509 error. Say so up front rather than let it
	// look like the backends are down.
	if strings.Contains(*backends, "https://") && !insecureBackends {
		log.Printf("lb: note — https:// backends with certificate verification ON; " +
			"add -insecure-backends if they use a self-signed certificate")
	}

	lb := &LoadBalancer{}
	lb.markStart()
	bs, err := parseBackends(*backends, *backendTimeout, lb)
	if err != nil {
		log.Fatalf("lb: %v", err)
	}
	lb.backends = bs

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go lb.healthLoop(ctx, *healthPath, *healthInterval, *healthTimeout)

	mux := http.NewServeMux()
	mux.HandleFunc("/lb/health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true, "uptime_s": round2(lb.uptime().Seconds())})
	})
	mux.HandleFunc("/lb/status", lb.handleStatus)
	mux.HandleFunc("/lb/metrics", lb.handleMetrics)
	// Zeroing between experiments is what makes the LB-side numbers in the
	// report per-experiment rather than cumulative.
	mux.HandleFunc("/lb/reset", func(w http.ResponseWriter, r *http.Request) {
		lb.metrics.reset()
		for _, b := range lb.backends {
			b.Requests.Store(0)
			b.Errors.Store(0)
		}
		lb.markStart()
		writeJSON(w, http.StatusOK, map[string]any{"reset": true})
	})
	mux.Handle("/", lb)

	srv := &http.Server{
		Addr:    *listen,
		Handler: mux,
		// No WriteTimeout and no ReadTimeout: a WebSocket connection is a
		// long-lived read and a long-lived write, and either timeout would
		// sever every chat session on a fixed schedule.
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       120 * time.Second,
		ErrorLog:          log.New(serverErrorLog{out: os.Stderr, count: &lb.metrics.TLSHandshakes}, "", log.LstdFlags),
	}

	scheme := "http"
	if *tlsCert != "" {
		scheme = "https"
	}
	log.Printf("lb: listening on %s (%s)", *listen, scheme)
	for _, b := range lb.backends {
		log.Printf("lb: backend %s (health %s%s)", b.URL, strings.TrimRight(b.URL.String(), "/"), *healthPath)
	}

	go func() {
		<-ctx.Done()
		log.Printf("lb: shutting down")
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(sctx)
	}()

	var serveErr error
	if *tlsCert != "" {
		// Go negotiates HTTP/2 over TLS by default. Left on, the load balancer
		// would speak h2 to the load generator and HTTP/1.1 to the backends,
		// so the two experiments would not be comparable with the plain-HTTP
		// runs. Pinning h1 keeps every configuration measuring the same thing.
		srv.TLSNextProto = map[string]func(*http.Server, *tls.Conn, http.Handler){}
		serveErr = srv.ListenAndServeTLS(*tlsCert, *tlsKey)
	} else {
		serveErr = srv.ListenAndServe()
	}
	if serveErr != nil && serveErr != http.ErrServerClosed {
		log.Fatalf("lb: %v", serveErr)
	}
}
