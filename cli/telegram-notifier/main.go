package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

var (
	version = "0.1.0"
	commit  = "dev"
)

const (
	defaultBaseURL = "http://127.0.0.1:8818"
	defaultSource  = "telegram-notifier-cli"
	oauthClientID  = "telegram-notifier-cli"
)

type options struct {
	baseURL string
	source  string
}

type storedCredential struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token,omitempty"`
	TokenType    string `json:"token_type,omitempty"`
	ExpiresIn    int    `json:"expires_in,omitempty"`
	CreatedAt    string `json:"created_at"`
	BaseURL      string `json:"base_url"`
}

type apiFailure struct {
	Status int
	Body   string
}

func (e *apiFailure) Error() string {
	return fmt.Sprintf("request failed with HTTP %d: %s", e.Status, e.Body)
}

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(argv []string) int {
	global := flag.NewFlagSet("telegram-notifier", flag.ContinueOnError)
	global.SetOutput(io.Discard)
	baseURL := global.String("base-url", envOr("TELEGRAM_NOTIFIER_BASE_URL", defaultBaseURL), "Telegram Notifier origin")
	source := global.String("source", envOr("TELEGRAM_NOTIFIER_SOURCE", defaultSource), "X-Notifier-Source identity")
	if err := global.Parse(argv); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	args := global.Args()
	if len(args) == 0 {
		printUsage()
		return 2
	}

	normalized, err := validateBaseURL(*baseURL)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	opts := options{baseURL: normalized, source: strings.TrimSpace(*source)}
	if opts.source == "" {
		fmt.Fprintln(os.Stderr, "source must not be empty")
		return 2
	}

	var commandErr error
	switch args[0] {
	case "version", "--version", "-version":
		fmt.Printf("telegram-notifier %s (%s)\n", version, commit)
		return 0
	case "auth":
		commandErr = runAuth(opts, args[1:])
	case "inbox":
		commandErr = runInbox(opts, args[1:])
	case "notify":
		commandErr = runNotify(opts, args[1:])
	case "reply":
		commandErr = runReply(opts, args[1:])
	case "download":
		commandErr = runDownload(opts, args[1:])
	default:
		printUsage()
		return 2
	}
	if commandErr != nil {
		token, _ := resolveToken(false)
		fmt.Fprintln(os.Stderr, redact(commandErr.Error(), token))
		return 1
	}
	return 0
}

func printUsage() {
	fmt.Fprintln(os.Stderr, "Telegram Notifier standalone CLI")
	fmt.Fprintln(os.Stderr, "usage: telegram-notifier [--base-url URL] [--source NAME] <command>")
	fmt.Fprintln(os.Stderr, "commands: version, auth login|status|logout, inbox, notify, reply, download")
}

func runAuth(opts options, argv []string) error {
	if len(argv) != 1 {
		return errors.New("usage: telegram-notifier auth login|status|logout")
	}
	switch argv[0] {
	case "status":
		token, source, err := resolveTokenWithSource(false)
		status := map[string]any{"authenticated": token != "", "source": source, "base_url": opts.baseURL}
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			status["warning"] = err.Error()
		}
		return printJSON(status)
	case "login":
		return oauthLogin(opts)
	case "logout":
		path, err := credentialPath()
		if err != nil {
			return err
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		return printJSON(map[string]any{"ok": true, "authenticated": false})
	default:
		return errors.New("usage: telegram-notifier auth login|status|logout")
	}
}

func runInbox(opts options, argv []string) error {
	fs := flag.NewFlagSet("inbox", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	after := fs.String("after", "", "cursor")
	limit := fs.Int("limit", 50, "1..200")
	if err := fs.Parse(argv); err != nil {
		return err
	}
	if *limit < 1 || *limit > 200 {
		return errors.New("limit must be 1..200")
	}
	query := url.Values{}
	query.Set("limit", strconv.Itoa(*limit))
	if *after != "" {
		query.Set("after", *after)
	}
	result, err := apiRequest(opts, http.MethodGet, "/v1/inbox?"+query.Encode(), nil, "")
	if err != nil {
		return err
	}
	return printRawJSON(result)
}

func runNotify(opts options, argv []string) error {
	fs := flag.NewFlagSet("notify", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	text := fs.String("text", "", "message text")
	title := fs.String("title", "", "optional title")
	idem := fs.String("idempotency-key", "", "optional stable idempotency key")
	if err := fs.Parse(argv); err != nil {
		return err
	}
	if strings.TrimSpace(*text) == "" {
		return errors.New("--text is required")
	}
	key, err := normalizeIdempotencyKey(*idem)
	if err != nil {
		return err
	}
	payload := map[string]any{"kind": "text", "title": *title, "text": *text}
	result, err := apiRequest(opts, http.MethodPost, "/v1/notify", payload, key)
	if err != nil {
		return err
	}
	return printRawJSON(result)
}

func runReply(opts options, argv []string) error {
	fs := flag.NewFlagSet("reply", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	eventID := fs.String("event-id", "", "inbound event id")
	text := fs.String("text", "", "reply text")
	title := fs.String("title", "", "optional title")
	idem := fs.String("idempotency-key", "", "optional stable idempotency key")
	if err := fs.Parse(argv); err != nil {
		return err
	}
	if strings.TrimSpace(*eventID) == "" || strings.TrimSpace(*text) == "" {
		return errors.New("--event-id and --text are required")
	}
	key, err := normalizeIdempotencyKey(*idem)
	if err != nil {
		return err
	}
	payload := map[string]any{"event_id": *eventID, "kind": "text", "title": *title, "text": *text}
	result, err := apiRequest(opts, http.MethodPost, "/v1/reply", payload, key)
	if err != nil {
		return err
	}
	return printRawJSON(result)
}

func runDownload(opts options, argv []string) error {
	fs := flag.NewFlagSet("download", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	eventID := fs.String("event-id", "", "inbound event id")
	output := fs.String("output", "", "output path")
	if err := fs.Parse(argv); err != nil {
		return err
	}
	if strings.TrimSpace(*eventID) == "" || strings.TrimSpace(*output) == "" {
		return errors.New("--event-id and --output are required")
	}
	query := url.Values{"event_id": []string{*eventID}}
	result, err := apiRequest(opts, http.MethodGet, "/v1/file?"+query.Encode(), nil, "")
	if err != nil {
		return err
	}
	var decoded struct {
		Filename      string `json:"filename"`
		ContentType   string `json:"content_type"`
		ContentBase64 string `json:"content_base64"`
	}
	if err := json.Unmarshal(result, &decoded); err != nil {
		return errors.New("invalid file response")
	}
	content, err := base64.StdEncoding.DecodeString(decoded.ContentBase64)
	if err != nil {
		return errors.New("invalid file base64")
	}
	if err := os.WriteFile(*output, content, 0o600); err != nil {
		return err
	}
	return printJSON(map[string]any{
		"ok": true, "output": *output, "filename": decoded.Filename,
		"content_type": decoded.ContentType, "bytes": len(content),
	})
}

func apiRequest(opts options, method, path string, payload any, idempotencyKey string) ([]byte, error) {
	safePath, err := validatePublicPath(path)
	if err != nil {
		return nil, err
	}
	token, _, err := resolveTokenWithSource(false)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}

	var body []byte
	if payload != nil {
		body, err = json.Marshal(payload)
		if err != nil {
			return nil, err
		}
	}
	if method != http.MethodGet && idempotencyKey == "" {
		idempotencyKey, err = newID("tncli")
		if err != nil {
			return nil, err
		}
	}

	client := &http.Client{Timeout: 20 * time.Second}
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		req, err := http.NewRequest(method, opts.baseURL+safePath, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Accept", "application/json")
		req.Header.Set("X-Notifier-Source", opts.source)
		req.Header.Set("User-Agent", "agentforge-telegram-notifier-cli/"+version)
		if payload != nil {
			req.Header.Set("Content-Type", "application/json")
		}
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		if idempotencyKey != "" {
			req.Header.Set("Idempotency-Key", idempotencyKey)
		}

		resp, err := client.Do(req)
		if err != nil {
			lastErr = errors.New(redact(err.Error(), token))
			if attempt < 2 {
				time.Sleep(time.Duration(250*(1<<attempt)) * time.Millisecond)
				continue
			}
			break
		}
		raw, readErr := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
		resp.Body.Close()
		if readErr != nil {
			return nil, readErr
		}
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			return raw, nil
		}
		safeBody := redact(strings.TrimSpace(string(raw)), token)
		if len(safeBody) > 2000 {
			safeBody = safeBody[:2000]
		}
		lastErr = &apiFailure{Status: resp.StatusCode, Body: safeBody}
		if attempt < 2 && retryableStatus(resp.StatusCode) {
			if wait := retryAfter(resp.Header.Get("Retry-After")); wait > 0 {
				time.Sleep(wait)
			} else {
				time.Sleep(time.Duration(250*(1<<attempt)) * time.Millisecond)
			}
			continue
		}
		break
	}
	if lastErr == nil {
		lastErr = errors.New("request failed")
	}
	return nil, lastErr
}

func validatePublicPath(raw string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil || u.IsAbs() || u.Host != "" || !strings.HasPrefix(u.Path, "/v1/") {
		return "", errors.New("request path must be a relative public /v1/* path")
	}
	lower := strings.ToLower(u.Path)
	for _, prefix := range []string{"/v1/admin", "/v1/internal", "/v1/saas-admin"} {
		if lower == prefix || strings.HasPrefix(lower, prefix+"/") {
			return "", errors.New("request path is not public")
		}
	}
	for _, part := range strings.Split(u.Path, "/") {
		if part == "." || part == ".." {
			return "", errors.New("request path traversal is not allowed")
		}
	}
	if strings.Contains(strings.ToLower(raw), "%2e") || strings.Contains(raw, "\\") {
		return "", errors.New("encoded path traversal is not allowed")
	}
	return u.RequestURI(), nil
}

func validateBaseURL(raw string) (string, error) {
	raw = strings.TrimRight(strings.TrimSpace(raw), "/")
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.Path != "" || u.RawQuery != "" || u.Fragment != "" || u.User != nil {
		return "", errors.New("base URL must be an origin")
	}
	if u.Scheme == "https" {
		return raw, nil
	}
	host := strings.ToLower(u.Hostname())
	if u.Scheme == "http" && (host == "127.0.0.1" || host == "localhost" || host == "::1") {
		return raw, nil
	}
	return "", errors.New("remote base URLs must use HTTPS")
}

func normalizeIdempotencyKey(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", nil
	}
	if len(raw) < 8 || len(raw) > 200 {
		return "", errors.New("idempotency key must be 8..200 characters")
	}
	return raw, nil
}

func retryableStatus(status int) bool {
	return status == http.StatusTooManyRequests || status == http.StatusBadGateway ||
		status == http.StatusServiceUnavailable || status == http.StatusGatewayTimeout
}

func retryAfter(value string) time.Duration {
	seconds, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil || seconds < 1 || seconds > 60 {
		return 0
	}
	return time.Duration(seconds) * time.Second
}

func oauthLogin(opts options) error {
	verifier, err := newID("")
	if err != nil {
		return err
	}
	verifier += verifier
	sum := sha256.Sum256([]byte(verifier))
	challenge := base64.RawURLEncoding.EncodeToString(sum[:])
	state, err := newID("state")
	if err != nil {
		return err
	}

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	defer listener.Close()
	redirectURI := "http://" + listener.Addr().String() + "/callback"

	authURL, _ := url.Parse(opts.baseURL + "/oauth/authorize")
	query := authURL.Query()
	query.Set("response_type", "code")
	query.Set("client_id", oauthClientID)
	query.Set("redirect_uri", redirectURI)
	query.Set("code_challenge", challenge)
	query.Set("code_challenge_method", "S256")
	query.Set("state", state)
	query.Set("source", opts.source)
	authURL.RawQuery = query.Encode()

	codeCh := make(chan string, 1)
	errCh := make(chan error, 1)
	server := &http.Server{ReadHeaderTimeout: 5 * time.Second}
	server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/callback" {
			http.NotFound(w, r)
			return
		}
		if r.URL.Query().Get("state") != state {
			http.Error(w, "OAuth state mismatch", http.StatusBadRequest)
			errCh <- errors.New("OAuth state mismatch")
			return
		}
		if protocolErr := r.URL.Query().Get("error"); protocolErr != "" {
			http.Error(w, "OAuth authorization failed", http.StatusBadRequest)
			errCh <- fmt.Errorf("OAuth authorization failed: %s", protocolErr)
			return
		}
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "OAuth code missing", http.StatusBadRequest)
			errCh <- errors.New("OAuth code missing")
			return
		}
		fmt.Fprintln(w, "Telegram Notifier authentication complete. You can close this window.")
		codeCh <- code
	})

	fmt.Println("Open this URL to authenticate:")
	fmt.Println(authURL.String())
	_ = openBrowser(authURL.String())

	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	var code string
	select {
	case code = <-codeCh:
	case err = <-errCh:
		return err
	case <-ctx.Done():
		return errors.New("OAuth login timed out")
	}
	_ = server.Shutdown(context.Background())

	form := url.Values{
		"grant_type":    []string{"authorization_code"},
		"client_id":     []string{oauthClientID},
		"code":          []string{code},
		"redirect_uri":  []string{redirectURI},
		"code_verifier": []string{verifier},
	}
	req, err := http.NewRequest(http.MethodPost, opts.baseURL+"/oauth/token", strings.NewReader(form.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := (&http.Client{Timeout: 20 * time.Second}).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("OAuth token exchange failed with HTTP %d", resp.StatusCode)
	}
	var credential storedCredential
	if err := json.Unmarshal(raw, &credential); err != nil || credential.AccessToken == "" {
		return errors.New("OAuth token response was invalid")
	}
	credential.CreatedAt = time.Now().UTC().Format(time.RFC3339)
	credential.BaseURL = opts.baseURL
	if credential.TokenType == "" {
		credential.TokenType = "Bearer"
	}
	if err := saveCredential(credential); err != nil {
		return err
	}
	return printJSON(map[string]any{"ok": true, "authenticated": true, "base_url": opts.baseURL})
}

func openBrowser(target string) error {
	var command *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		command = exec.Command("open", target)
	case "windows":
		command = exec.Command("rundll32", "url.dll,FileProtocolHandler", target)
	default:
		command = exec.Command("xdg-open", target)
	}
	return command.Start()
}

func resolveToken(require bool) (string, error) {
	token, _, err := resolveTokenWithSource(require)
	return token, err
}

func resolveTokenWithSource(require bool) (string, string, error) {
	if token := strings.TrimSpace(os.Getenv("TELEGRAM_NOTIFIER_TOKEN")); token != "" {
		return token, "environment", nil
	}
	if path := strings.TrimSpace(os.Getenv("TELEGRAM_NOTIFIER_TOKEN_FILE")); path != "" {
		info, err := os.Stat(path)
		if err != nil {
			return "", "file", err
		}
		if runtime.GOOS != "windows" && info.Mode().Perm()&0o077 != 0 {
			return "", "file", errors.New("token file must not be group/world readable")
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return "", "file", err
		}
		if token := strings.TrimSpace(string(raw)); token != "" {
			return token, "file", nil
		}
	}
	credential, err := loadCredential()
	if err == nil && strings.TrimSpace(credential.AccessToken) != "" {
		return strings.TrimSpace(credential.AccessToken), "oauth", nil
	}
	if require {
		return "", "", errors.New("authentication required; run 'telegram-notifier auth login' or set TELEGRAM_NOTIFIER_TOKEN")
	}
	if errors.Is(err, os.ErrNotExist) {
		return "", "none", os.ErrNotExist
	}
	return "", "none", err
}

func credentialPath() (string, error) {
	if override := strings.TrimSpace(os.Getenv("TELEGRAM_NOTIFIER_CREDENTIAL_FILE")); override != "" {
		return override, nil
	}
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(base, "agentforge", "telegram-notifier", "credentials.json"), nil
}

func saveCredential(value storedCredential) error {
	path, err := credentialPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o600); err != nil {
		return err
	}
	if err := os.Chmod(tmp, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func loadCredential() (storedCredential, error) {
	var value storedCredential
	path, err := credentialPath()
	if err != nil {
		return value, err
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return value, err
	}
	err = json.Unmarshal(raw, &value)
	return value, err
}

func newID(prefix string) (string, error) {
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	value := base64.RawURLEncoding.EncodeToString(raw)
	if prefix != "" {
		return prefix + "-" + value, nil
	}
	return value, nil
}

func redact(value, secret string) string {
	if secret == "" {
		return value
	}
	return strings.ReplaceAll(value, secret, "[REDACTED]")
}

func printJSON(value any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	fmt.Println(string(raw))
	return nil
}

func printRawJSON(raw []byte) error {
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		return errors.New("server returned invalid JSON")
	}
	return printJSON(value)
}

func envOr(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}
