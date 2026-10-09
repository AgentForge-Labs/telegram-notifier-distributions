# frozen_string_literal: true

require "minitest/autorun"
require_relative "../lib/agentforge-telegram-notifier"

class FakeTransport
  attr_reader :calls
  attr_accessor :responses

  def initialize
    @calls = []
    @responses = []
  end

  def send(method, url, headers, body, timeout)
    @calls << { method: method, url: url, headers: headers.dup, body: body, timeout: timeout }
    raise "no fake response" if @responses.empty?

    @responses.shift
  end
end

class TelegramNotifierClientTest < Minitest::Test
  Client = AgentForge::TelegramNotifier::Client
  AuthError = AgentForge::TelegramNotifier::AuthError
  QuotaError = AgentForge::TelegramNotifier::QuotaError
  DeliveryError = AgentForge::TelegramNotifier::DeliveryError

  def test_default_origin_and_version
    client = Client.new(source: "agent-a")
    assert_equal "http://127.0.0.1:8818", client.origin
    assert_equal "0.2.0", AgentForge::TelegramNotifier::VERSION
  end

  def test_source_and_origin_validation
    assert_raises(ArgumentError) { Client.new(source: "") }
    assert_raises(ArgumentError) { Client.new(source: "agent-a", origin: "http://example.test") }
    assert_raises(ArgumentError) { Client.new(source: "agent-a", origin: "https://example.test/base") }
    client = Client.new(source: "agent-a", origin: "https://notify.example.test")
    assert_equal "https://notify.example.test", client.origin
  end

  def test_inspect_redacts_optional_credential
    client = Client.new(source: "agent-a", key: "super-secret-key")
    refute_includes client.inspect, "super-secret-key"
    assert_includes client.inspect, "[REDACTED]"
  end

  def test_notify_retry_reuses_idempotency_and_identity_headers
    transport = FakeTransport.new
    transport.responses = [
      { status: 503, headers: {}, body: '{"error":"delivery_unavailable"}' },
      { status: 200, headers: {}, body: '{"ok":true,"delivery_id":"d1"}' }
    ]
    client = Client.new(
      source: "agent-a",
      key: "good-secret",
      origin: "https://notify.example.test",
      retries: 1,
      transport: transport
    )
    result = client.notify("hello")
    assert_equal "d1", result["delivery_id"]
    assert_equal 2, transport.calls.length

    first = transport.calls[0][:headers]
    second = transport.calls[1][:headers]
    assert_equal "agent-a", first["X-Notifier-Source"]
    assert_equal "Bearer good-secret", first["Authorization"]
    assert_operator first["Idempotency-Key"].length, :>=, 8
    assert_equal first["Idempotency-Key"], second["Idempotency-Key"]
    assert_equal "agentforge-telegram-notifier/0.2.0 ruby", first["User-Agent"]
  end

  def test_structured_errors_and_redaction
    auth_transport = FakeTransport.new
    auth_transport.responses = [
      { status: 401, headers: {}, body: '{"error":"credential leaked-secret rejected"}' }
    ]
    auth = assert_raises(AuthError) do
      Client.new(
        source: "agent-a", key: "leaked-secret",
        origin: "https://notify.example.test", transport: auth_transport
      ).inbox
    end
    refute_includes auth.message, "leaked-secret"
    assert_includes auth.message, "[REDACTED]"

    quota_transport = FakeTransport.new
    quota_transport.responses = [
      { status: 429, headers: {}, body: '{"code":"QUOTA_EXCEEDED","message":"limit","retryAfterSeconds":30}' }
    ]
    quota = assert_raises(QuotaError) do
      Client.new(
        source: "agent-a", key: "quota-secret",
        origin: "https://notify.example.test", retries: 3, transport: quota_transport
      ).inbox
    end
    assert_equal "QUOTA_EXCEEDED", quota.code
    assert_equal 30, quota.retry_after_seconds
    assert_equal 1, quota_transport.calls.length

    delivery_transport = FakeTransport.new
    delivery_transport.responses = [
      { status: 502, headers: {}, body: '{"code":"DELIVERY_FAILED","message":"failed"}' }
    ]
    assert_raises(DeliveryError) do
      Client.new(
        source: "agent-a", key: "delivery-secret",
        origin: "https://notify.example.test", retries: 0, transport: delivery_transport
      ).inbox
    end
  end

  def test_file_payloads_and_download
    transport = FakeTransport.new
    transport.responses = [
      { status: 200, headers: {}, body: '{"ok":true,"delivery_id":"d1"}' },
      {
        status: 200, headers: {},
        body: '{"ok":true,"filename":"hello.txt","content_type":"text/plain","content_base64":"aGVsbG8="}'
      }
    ]
    client = Client.new(source: "agent-a", origin: "https://notify.example.test", transport: transport)
    client.notify_file("hello", filename: "hello.txt", content_type: "text/plain")
    payload = JSON.parse(transport.calls[0][:body])
    assert_equal "aGVsbG8=", payload["content_base64"]

    file = client.download("e1")
    assert_equal "hello.txt", file["filename"]
    assert_equal "text/plain", file["content_type"]
    assert_equal "hello", file["content"]
  end

  def test_request_and_input_guards
    client = Client.new(source: "agent-a")
    assert_raises(ArgumentError) { client.request("GET", "https://evil.example/v1/inbox") }
    assert_raises(ArgumentError) { client.request("GET", "/v1/admin/users") }
    assert_raises(ArgumentError) { client.request("GET", "/v1/../admin") }
    assert_raises(ArgumentError) { client.reply_file("e1", "body", filename: "../bad.txt") }
    assert_raises(ArgumentError) { client.download("../e1") }
  end
end
