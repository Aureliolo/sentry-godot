extends GdUnitTestSuite
## Metrics never leave the device while consent is withheld, even with every automatic metric
## enabled, and flow once it is given.
##
## The DSN points at a listener this suite runs on the loopback interface, so what counts is what
## reached the network, not what the SDK captured.

const METRIC_ITEM := "\"type\":\"trace_metric\""
# Longer than the native batcher's five-second flush, so a batch would have gone out by then.
const QUIET_USEC := 6_500_000

var _server := TCPServer.new()
var _port := 0
var _peers: Array[StreamPeerTCP] = []
var _pending: Dictionary = {}
var _envelopes: PackedStringArray = []


func before() -> void:
	for candidate in range(47100, 47200):
		if _server.listen(candidate, "127.0.0.1") == OK:
			_port = candidate
			break
	assert_int(_port).is_not_zero()


func after() -> void:
	SentrySDK.reset_user_consent()
	SentrySDK.close()
	for peer in _peers:
		peer.disconnect_from_host()
	_server.stop()


func _init_sdk() -> void:
	SentrySDK.init(func(options: SentryOptions) -> void:
		options.dsn = "http://public@127.0.0.1:%d/42" % _port
		options.require_user_consent = true
		options.auto_metrics.enable_frame_metrics = true
		options.auto_metrics.enable_rendering_metrics = true
		options.auto_metrics.enable_memory_metrics = true
		options.auto_metrics.frame_metrics_interval_sec = 1.0
		options.auto_metrics.rendering_metrics_interval_sec = 1.0
		options.auto_metrics.memory_metrics_interval_sec = 1.0
	)
	assert_bool(SentrySDK.is_enabled()).is_true()


## Accepts connections and answers each complete request with 200, keeping its body.
func _serve() -> void:
	while _server.is_connection_available():
		var peer := _server.take_connection()
		_peers.append(peer)
		_pending[peer] = PackedByteArray()
	for peer in _peers.duplicate():
		peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			_peers.erase(peer)
			_pending.erase(peer)
			continue
		var available := peer.get_available_bytes()
		if available > 0:
			var buffer: PackedByteArray = _pending[peer]
			buffer.append_array(peer.get_data(available)[1])
			_pending[peer] = buffer
		_take_request(peer)


func _take_request(peer: StreamPeerTCP) -> void:
	var data: PackedByteArray = _pending[peer]
	var text := data.get_string_from_ascii()
	var end := text.find("\r\n\r\n")
	if end < 0:
		return
	var head := text.substr(0, end).to_lower()
	var length := 0
	var gzip := false
	for line in head.split("\r\n"):
		if line.begins_with("content-length:"):
			length = line.get_slice(":", 1).strip_edges().to_int()
		elif line.begins_with("content-encoding:") and line.contains("gzip"):
			gzip = true
	if head.contains("expect: 100-continue") and data.size() == end + 4:
		peer.put_data("HTTP/1.1 100 Continue\r\n\r\n".to_ascii_buffer())
		return
	if data.size() < end + 4 + length:
		return
	var body := data.slice(end + 4, end + 4 + length)
	if gzip:
		body = body.decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)
	_envelopes.append(body.get_string_from_utf8())
	_pending[peer] = data.slice(end + 4 + length)
	peer.put_data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}".to_ascii_buffer())


func _metric_envelopes() -> int:
	var count := 0
	for envelope in _envelopes:
		if envelope.contains(METRIC_ITEM):
			count += 1
	return count


func _serve_for(duration_usec: int) -> void:
	var deadline := Time.get_ticks_usec() + duration_usec
	while Time.get_ticks_usec() < deadline:
		_serve()
		await get_tree().process_frame


func test_metrics_wait_for_consent(_timeout: int = 30000) -> void:
	_init_sdk()
	SentrySDK.revoke_user_consent()
	for i in 20:
		SentrySDK.metrics.count("consent.withheld", 1)
		SentrySDK.metrics.gauge("consent.withheld_gauge", float(i))
	await _serve_for(QUIET_USEC)
	assert_int(_metric_envelopes()) \
		.override_failure_message("a metric reached the network while consent was withheld") \
		.is_zero()

	SentrySDK.give_user_consent()
	for i in 20:
		SentrySDK.metrics.count("consent.given", 1)
	var deadline := Time.get_ticks_usec() + QUIET_USEC * 2
	while _metric_envelopes() == 0 and Time.get_ticks_usec() < deadline:
		_serve()
		await get_tree().process_frame
	assert_int(_metric_envelopes()) \
		.override_failure_message("no metric reached the network once consent was given") \
		.is_greater(0)
	for envelope in _envelopes:
		assert_str(envelope) \
			.override_failure_message("a metric captured while consent was withheld went out after it was given") \
			.not_contains("consent.withheld")
