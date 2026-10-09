package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
)

func TestWriteRetryReusesOneIdempotencyKey(t *testing.T) {
	t.Setenv("TELEGRAM_NOTIFIER_TOKEN", "super-secret-token")
	var mu sync.Mutex
	var keys []string
	attempts := 0

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		attempts++
		if got := r.Header.Get("X-Notifier-Source"); got != "test-source" {
			t.Errorf("source header = %q", got)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer super-secret-token" {
			t.Errorf("authorization header = %q", got)
		}
		keys = append(keys, r.Header.Get("Idempotency-Key"))
		w.Header().Set("Content-Type", "application/json")
		if attempts == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(`{"error":"temporary"}`))
			return
		}
		_, _ = w.Write([]byte(`{"ok":true,"delivery_id":"d1"}`))
	}))
	defer server.Close()

	raw, err := apiRequest(
		options{baseURL: server.URL, source: "test-source"},
		http.MethodPost,
		"/v1/notify",
		map[string]any{"kind": "text", "text": "hello"},
		"",
	)
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["ok"] != true {
		t.Fatalf("unexpected response: %s", raw)
	}
	if attempts != 2 {
		t.Fatalf("attempts=%d", attempts)
	}
	if len(keys) != 2 || keys[0] == "" || keys[0] != keys[1] {
		t.Fatalf("idempotency keys=%v", keys)
	}
}

func TestCredentialIsRedactedFromErrors(t *testing.T) {
	t.Setenv("TELEGRAM_NOTIFIER_TOKEN", "secret-value")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"message":"secret-value rejected"}`))
	}))
	defer server.Close()

	_, err := apiRequest(
		options{baseURL: server.URL, source: "test-source"},
		http.MethodGet,
		"/v1/inbox?limit=1",
		nil,
		"",
	)
	if err == nil {
		t.Fatal("expected error")
	}
	if strings.Contains(err.Error(), "secret-value") {
		t.Fatalf("credential leaked: %v", err)
	}
	if !strings.Contains(err.Error(), "[REDACTED]") {
		t.Fatalf("redaction marker missing: %v", err)
	}
}

func TestBaseURLPolicy(t *testing.T) {
	for _, value := range []string{"http://127.0.0.1:8818", "http://localhost:8818", "https://notifier.example"} {
		if _, err := validateBaseURL(value); err != nil {
			t.Fatalf("%s rejected: %v", value, err)
		}
	}
	for _, value := range []string{"http://notifier.example", "ftp://notifier.example", "https://user:pass@notifier.example"} {
		if _, err := validateBaseURL(value); err == nil {
			t.Fatalf("%s should be rejected", value)
		}
	}
}

func TestPublicPathPolicy(t *testing.T) {
	for _, value := range []string{"/v1/inbox?limit=1", "/v1/notify", "/v1/reply", "/v1/file?event_id=e1"} {
		if _, err := validatePublicPath(value); err != nil {
			t.Fatalf("%s rejected: %v", value, err)
		}
	}
	for _, value := range []string{
		"https://evil.example/v1/inbox",
		"/v1/admin/users",
		"/v1/internal/status",
		"/v1/../admin",
		"/v1/%2e%2e/admin",
	} {
		if _, err := validatePublicPath(value); err == nil {
			t.Fatalf("%s should be rejected", value)
		}
	}
}

func TestTokenFileMustBePrivate(t *testing.T) {
	if os.PathSeparator == '\\' {
		t.Skip("POSIX permission policy")
	}
	dir := t.TempDir()
	path := dir + "/token"
	if err := os.WriteFile(path, []byte("token-value\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TELEGRAM_NOTIFIER_TOKEN", "")
	t.Setenv("TELEGRAM_NOTIFIER_TOKEN_FILE", path)
	if _, _, err := resolveTokenWithSource(false); err == nil {
		t.Fatal("expected private-file permission error")
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	token, source, err := resolveTokenWithSource(false)
	if err != nil {
		t.Fatal(err)
	}
	if token != "token-value" || source != "file" {
		t.Fatalf("token=%q source=%q", token, source)
	}
}
