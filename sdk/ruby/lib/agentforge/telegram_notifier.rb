# frozen_string_literal: true

require "base64"
require "json"
require "net/http"
require "openssl"
require "securerandom"
require "uri"

module AgentForge
  module TelegramNotifier
    VERSION = "0.2.0"
    DEFAULT_ORIGIN = "http://127.0.0.1:8818"
    USER_AGENT = "agentforge-telegram-notifier/#{VERSION} ruby"
    RETRYABLE = [429, 502, 503, 504].freeze

    class Error < StandardError
      attr_reader :status, :code, :body, :request_id, :retry_after_seconds

      def initialize(code, safe_message, status: 0, body: nil, request_id: nil, retry_after_seconds: nil)
        @status = status.to_i
        @code = code.to_s
        @body = body
        @request_id = request_id
        @retry_after_seconds = retry_after_seconds
        super("Telegram Notifier #{@code} (#{@status}): #{safe_message}")
      end
    end

    class AuthError < Error; end
    class QuotaError < Error; end
    class DeliveryError < Error; end
    class ValidationError < Error; end
    class TransportError < Error; end

    class NetHttpTransport
      def send(method, url, headers, body, timeout)
        uri = URI.parse(url)
        http = Net::HTTP.new(uri.host, uri.port)
        http.use_ssl = uri.scheme == "https"
        if http.use_ssl?
          http.verify_mode = OpenSSL::SSL::VERIFY_PEER
        end
        http.open_timeout = timeout
        http.read_timeout = timeout

        klass = {
          "GET" => Net::HTTP::Get,
          "POST" => Net::HTTP::Post,
          "PUT" => Net::HTTP::Put,
          "PATCH" => Net::HTTP::Patch,
          "DELETE" => Net::HTTP::Delete
        }.fetch(method)
        request = klass.new(uri.request_uri, headers)
        request.body = body unless body.nil?
        response = http.request(request)
        {
          status: response.code.to_i,
          headers: response.each_header.to_h,
          body: response.body.to_s
        }
      end
    end

    class Client
      attr_reader :source, :origin, :timeout, :retries

      def initialize(source:, key: nil, origin: DEFAULT_ORIGIN, timeout: 15, retries: 1, transport: nil)
        @source = source.to_s.strip
        raise ArgumentError, "source must not be empty" if @source.empty?

        @credential = optional(key)
        @origin = normalize_origin(origin)
        @timeout = Float(timeout)
        raise ArgumentError, "timeout must be positive" unless @timeout.positive?

        @retries = Integer(retries)
        raise ArgumentError, "retries must be non-negative" if @retries.negative?

        @transport = transport || NetHttpTransport.new
      rescue TypeError
        raise ArgumentError, "timeout/retries have invalid type"
      end

      def inspect
        credential = @credential.nil? ? "(none)" : "[REDACTED]"
        "#<AgentForge::TelegramNotifier::Client source=#{@source.inspect} credential=#{credential} origin=#{@origin.inspect}>"
      end

      alias to_s inspect

      def inbox(after: nil, limit: 50)
        limit = Integer(limit)
        raise ArgumentError, "limit must be between 1 and 500" unless limit.between?(1, 500)

        query = { "limit" => limit }
        query["after"] = after.to_s unless after.nil? || after.to_s.empty?
        request("GET", "/v1/inbox", query: query)
      end

      def notify(text, title: "", idempotency_key: nil)
        request(
          "POST",
          "/v1/notify",
          body: { "kind" => "text", "title" => title.to_s, "text" => text.to_s },
          idempotency_key: idempotency_key
        )
      end

      def notify_file(bytes, filename:, content_type: "application/octet-stream", photo: false,
                      caption: "", idempotency_key: nil)
        validate_filename!(filename)
        request(
          "POST",
          "/v1/notify",
          body: {
            "kind" => photo ? "photo" : "document",
            "filename" => filename.to_s,
            "content_type" => content_type.to_s,
            "content_base64" => Base64.strict_encode64(bytes.to_s.b),
            "text" => caption.to_s
          },
          idempotency_key: idempotency_key
        )
      end

      def reply(event_id, text, title: "", idempotency_key: nil)
        validate_event_id!(event_id)
        request(
          "POST",
          "/v1/reply",
          body: {
            "event_id" => event_id.to_s,
            "kind" => "text",
            "title" => title.to_s,
            "text" => text.to_s
          },
          idempotency_key: idempotency_key
        )
      end

      def reply_file(event_id, bytes, filename:, content_type: "application/octet-stream",
                     photo: false, caption: "", idempotency_key: nil)
        validate_event_id!(event_id)
        validate_filename!(filename)
        request(
          "POST",
          "/v1/reply",
          body: {
            "event_id" => event_id.to_s,
            "kind" => photo ? "photo" : "document",
            "filename" => filename.to_s,
            "content_type" => content_type.to_s,
            "content_base64" => Base64.strict_encode64(bytes.to_s.b),
            "text" => caption.to_s
          },
          idempotency_key: idempotency_key
        )
      end

      def download(event_id)
        validate_event_id!(event_id)
        result = request("GET", "/v1/file", query: { "event_id" => event_id.to_s })
        encoded = result["content_base64"]
        unless encoded.is_a?(String)
          raise TransportError.new("INVALID_FILE_PAYLOAD", "missing file payload")
        end
        begin
          content = Base64.strict_decode64(encoded)
        rescue ArgumentError
          raise TransportError.new("INVALID_FILE_PAYLOAD", "invalid file payload")
        end
        {
          "filename" => result["filename"].to_s,
          "content_type" => (result["content_type"] || "application/octet-stream").to_s,
          "content" => content
        }
      end

      def request(method, path, query: nil, body: nil, idempotency_key: nil, retry_request: true)
        method = method.to_s.upcase
        raise ArgumentError, "unsupported HTTP method" unless %w[GET POST PUT PATCH DELETE].include?(method)

        path = safe_path(path)
        payload = body.nil? ? nil : JSON.generate(body)
        key = method == "GET" ? nil : normalize_idempotency_key(idempotency_key)

        url = "#{@origin}#{path}"
        unless query.nil? || query.empty?
          raise ArgumentError, "query must be a Hash" unless query.is_a?(Hash)
          url += "?#{URI.encode_www_form(query)}"
        end

        headers = {
          "Accept" => "application/json",
          "X-Notifier-Source" => @source,
          "User-Agent" => USER_AGENT
        }
        headers["Authorization"] = "Bearer #{@credential}" unless @credential.nil?
        headers["Content-Type"] = "application/json" unless payload.nil?
        headers["Idempotency-Key"] = key unless key.nil?

        attempts = (retry_request && (method == "GET" || !key.nil?)) ? @retries + 1 : 1
        last_error = nil
        attempts.times do |attempt|
          response = begin
            @transport.send(method, url, headers, payload, @timeout)
          rescue StandardError
            nil
          end

          if response.nil?
            last_error = TransportError.new("NETWORK_ERROR", "network request failed")
            if attempt + 1 < attempts
              backoff(attempt)
              next
            end
            raise last_error
          end

          status = response.fetch(:status, 0).to_i
          raw = response.fetch(:body, "").to_s
          if status.between?(200, 299)
            return {} if raw.empty?
            begin
              decoded = JSON.parse(raw)
            rescue JSON::ParserError
              raise TransportError.new("INVALID_RESPONSE", "invalid JSON response", status: status)
            end
            unless decoded.is_a?(Hash)
              raise TransportError.new("INVALID_RESPONSE", "invalid JSON response", status: status)
            end
            return decoded
          end

          last_error = condition(status, raw)
          break if attempt + 1 >= attempts
          break unless RETRYABLE.include?(status)
          break if last_error.code == "QUOTA_EXCEEDED"
          backoff(attempt)
        end
        raise(last_error || TransportError.new("NETWORK_ERROR", "network request failed"))
      rescue JSON::GeneratorError
        raise ArgumentError, "body is not JSON encodable"
      end

      private

      def condition(status, raw)
        body = begin
          parsed = raw.empty? ? {} : JSON.parse(raw)
          parsed.is_a?(Hash) ? parsed : {}
        rescue JSON::ParserError
          {}
        end

        nested = body["error"]
        code = body["code"]
        message = body["message"]
        request_id = body["requestId"]
        retry_after = body["retryAfterSeconds"]

        if nested.is_a?(Hash)
          code ||= nested["code"]
          message ||= nested["message"]
          request_id ||= nested["requestId"]
          retry_after ||= nested["retryAfterSeconds"]
        elsif nested.is_a?(String)
          code ||= nested
          message ||= nested
        end

        code = redact((code.nil? || code.to_s.empty?) ? "REQUEST_FAILED" : code.to_s)
        message = redact((message.nil? || message.to_s.empty?) ? code : message.to_s)
        safe_body = redact_value(body)
        retry_after = Integer(retry_after) rescue nil
        kwargs = {
          status: status,
          body: safe_body,
          request_id: request_id.is_a?(String) ? request_id : nil,
          retry_after_seconds: retry_after
        }

        return AuthError.new(code, message, **kwargs) if [401, 403].include?(status)
        return QuotaError.new(code, message, **kwargs) if status == 429
        if [502, 503, 504].include?(status) || code.upcase.include?("DELIVERY")
          return DeliveryError.new(code, message, **kwargs)
        end
        if [400, 404, 409, 422].include?(status)
          return ValidationError.new(code, message, **kwargs)
        end
        Error.new(code, message, **kwargs)
      end

      def redact(value)
        return value if @credential.nil? || @credential.empty?
        value.gsub(@credential, "[REDACTED]")
      end

      def redact_value(value)
        case value
        when String then redact(value)
        when Array then value.map { |item| redact_value(item) }
        when Hash then value.transform_values { |item| redact_value(item) }
        else value
        end
      end

      def normalize_idempotency_key(value)
        key = optional(value) || SecureRandom.hex(16)
        raise ArgumentError, "invalid idempotency key length" unless key.length.between?(8, 200)
        key
      end

      def validate_event_id!(value)
        text = value.to_s
        if text.empty? || text.include?("/") || text.include?("\\")
          raise ArgumentError, "invalid event id"
        end
      end

      def validate_filename!(value)
        text = value.to_s
        if text.empty? || text.include?("/") || text.include?("\\")
          raise ArgumentError, "invalid filename"
        end
      end

      def safe_path(value)
        path = value.to_s
        raise ArgumentError, "path must be a relative public /v1/* path" unless path.start_with?("/v1/")
        raise ArgumentError, "absolute URLs are not allowed" if path.match?(/^[a-z][a-z0-9+.-]*:\/\//i)
        if path.match?(/%(?:2f|5c|2e|25)/i)
          raise ArgumentError, "encoded traversal or separators are not allowed"
        end

        decoded = URI::DEFAULT_PARSER.unescape(path)
        raise ArgumentError, "invalid path" if decoded.include?("\\") || decoded.include?("//")
        segments = decoded.split("/")
        raise ArgumentError, "path traversal is not allowed" if segments.any? { |part| part == "." || part == ".." }

        lower = decoded.downcase
        %w[/v1/admin /v1/internal /v1/saas-admin].each do |prefix|
          if lower == prefix || lower.start_with?("#{prefix}/")
            raise ArgumentError, "private API path is not allowed"
          end
        end
        decoded
      end

      def normalize_origin(value)
        origin = value.to_s.strip.sub(%r{/+\z}, "")
        uri = URI.parse(origin)
        unless %w[http https].include?(uri.scheme) && uri.host && !uri.host.empty?
          raise ArgumentError, "origin must be an http(s) origin"
        end
        if uri.user || uri.password || uri.query || uri.fragment || !(uri.path.nil? || uri.path.empty? || uri.path == "/")
          raise ArgumentError, "origin must not include credentials, path, query or fragment"
        end
        if uri.scheme == "http" && !%w[127.0.0.1 localhost ::1].include?(uri.host.downcase)
          raise ArgumentError, "insecure HTTP is allowed only for loopback origins"
        end
        origin
      rescue URI::InvalidURIError
        raise ArgumentError, "origin must be an http(s) origin"
      end

      def optional(value)
        return nil if value.nil?
        text = value.to_s.strip
        text.empty? ? nil : text
      end

      def backoff(attempt)
        sleep([0.05 * (2**attempt), 0.25].min)
      end
    end
  end
end
