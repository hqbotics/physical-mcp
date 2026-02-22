import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:physical_mcp_app/models/server_config.dart';
import 'package:physical_mcp_app/services/api_client.dart';

void main() {
  const testConfig = ServerConfig(
    name: 'Test Server',
    host: '127.0.0.1',
    port: 8090,
  );

  const authConfig = ServerConfig(
    name: 'Auth Server',
    host: '127.0.0.1',
    port: 8090,
    authToken: 'test-token',
  );

  group('ApiClient.isHealthy', () {
    test('returns true on 200 response', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/health');
        return http.Response('{"status": "ok"}', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final result = await api.isHealthy();
      expect(result, true);
    });

    test('returns false on 500 response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final result = await api.isHealthy();
      expect(result, false);
    });

    test('returns false on 404 response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final result = await api.isHealthy();
      expect(result, false);
    });

    test('returns false on network error (connection refused)', () async {
      final mockClient = MockClient((request) async {
        throw Exception('Connection refused');
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final result = await api.isHealthy();
      expect(result, false);
    });

    test('sends correct URL', () async {
      Uri? capturedUrl;
      final mockClient = MockClient((request) async {
        capturedUrl = request.url;
        return http.Response('{"status": "ok"}', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      await api.isHealthy();
      expect(capturedUrl.toString(), 'http://127.0.0.1:8090/health');
    });
  });

  group('ApiClient.getCameras', () {
    test('parses list of cameras', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/cameras');
        return http.Response(
          jsonEncode([
            {'id': 'usb:0', 'name': 'Front', 'type': 'usb', 'enabled': true},
            {'id': 'rtsp:1', 'name': 'Back', 'type': 'rtsp', 'enabled': false},
          ]),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final cameras = await api.getCameras();
      expect(cameras, hasLength(2));
      expect(cameras[0].id, 'usb:0');
      expect(cameras[0].name, 'Front');
      expect(cameras[1].id, 'rtsp:1');
      expect(cameras[1].enabled, false);
    });

    test('returns empty list on empty response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('[]', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final cameras = await api.getCameras();
      expect(cameras, isEmpty);
    });

    test('returns empty list on non-list response', () async {
      final mockClient = MockClient((request) async {
        return http.Response('{"error": "no cameras"}', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final cameras = await api.getCameras();
      expect(cameras, isEmpty);
    });

    test('throws ApiException on 500', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Server Error', 500);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      expect(() => api.getCameras(), throwsA(isA<ApiException>()));
    });
  });

  group('ApiClient.getRules', () {
    test('parses list of rules', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/rules');
        return http.Response(
          jsonEncode([
            {
              'id': 'r_1',
              'name': 'Door watch',
              'condition': 'person at door',
              'priority': 'high',
              'enabled': true,
              'created_at': '2026-02-20T10:00:00',
            },
          ]),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final rules = await api.getRules();
      expect(rules, hasLength(1));
      expect(rules[0].name, 'Door watch');
      expect(rules[0].priority, 'high');
    });

    test('returns empty list on empty array', () async {
      final mockClient = MockClient((request) async {
        return http.Response('[]', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final rules = await api.getRules();
      expect(rules, isEmpty);
    });
  });

  group('ApiClient.getAlerts', () {
    test('parses list of alerts', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/alerts');
        expect(request.url.queryParameters['limit'], '50');
        return http.Response(
          jsonEncode([
            {
              'id': 'a_1',
              'rule_id': 'r_1',
              'rule_name': 'Door watch',
              'priority': 'high',
              'reasoning': 'Person detected',
              'confidence': 0.9,
              'timestamp': '2026-02-20T12:00:00',
            },
          ]),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final alerts = await api.getAlerts();
      expect(alerts, hasLength(1));
      expect(alerts[0].reasoning, 'Person detected');
      expect(alerts[0].confidence, 0.9);
    });

    test('respects custom limit parameter', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.queryParameters['limit'], '10');
        return http.Response('[]', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      await api.getAlerts(limit: 10);
    });
  });

  group('ApiClient.openCameras', () {
    test('sends POST and returns count', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/cameras/open');
        return http.Response(
          jsonEncode({
            'opened': ['usb:0', 'usb:1'],
            'failed': [],
            'count': 2,
          }),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final count = await api.openCameras();
      expect(count, 2);
    });

    test('returns 0 when no cameras configured', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({'opened': [], 'failed': [], 'count': 0}),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final count = await api.openCameras();
      expect(count, 0);
    });
  });

  group('ApiClient.createRule', () {
    test('sends correct POST body', () async {
      Map<String, dynamic>? capturedBody;
      final mockClient = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/rules');
        expect(request.headers['Content-Type'], 'application/json');
        capturedBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': 'r_new',
            'name': 'New Rule',
            'condition': 'cat on couch',
            'priority': 'medium',
            'notification_type': 'local',
            'cooldown_seconds': 60,
            'enabled': true,
            'trigger_count': 0,
            'created_at': '2026-02-20T15:00:00',
          }),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final rule = await api.createRule(
        name: 'New Rule',
        condition: 'cat on couch',
        cameraId: 'usb:0',
        priority: 'medium',
        notificationType: 'local',
        cooldownSeconds: 60,
      );

      expect(capturedBody, isNotNull);
      expect(capturedBody!['name'], 'New Rule');
      expect(capturedBody!['condition'], 'cat on couch');
      expect(capturedBody!['camera_id'], 'usb:0');
      expect(rule.id, 'r_new');
      expect(rule.name, 'New Rule');
    });
  });

  group('ApiClient.deleteRule', () {
    test('sends DELETE request with rule ID in path', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'DELETE');
        expect(request.url.path, '/rules/r_123');
        return http.Response('{"status": "deleted"}', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      await api.deleteRule('r_123');
      // No exception means success
    });

    test('throws on 404 (rule not found)', () async {
      final mockClient = MockClient((request) async {
        return http.Response('Not found', 404);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      expect(() => api.deleteRule('r_nonexistent'), throwsA(isA<ApiException>()));
    });
  });

  group('ApiClient.toggleRule', () {
    test('sends PUT request and returns updated rule', () async {
      final mockClient = MockClient((request) async {
        expect(request.method, 'PUT');
        expect(request.url.path, '/rules/r_123/toggle');
        return http.Response(
          jsonEncode({
            'id': 'r_123',
            'name': 'Test Rule',
            'condition': 'test',
            'priority': 'medium',
            'enabled': false, // toggled
            'created_at': '2026-02-20T10:00:00',
          }),
          200,
        );
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      final rule = await api.toggleRule('r_123');
      expect(rule.enabled, false);
    });
  });

  group('ApiClient auth headers', () {
    test('sends Authorization header when token configured', () async {
      Map<String, String>? capturedHeaders;
      final mockClient = MockClient((request) async {
        capturedHeaders = request.headers;
        return http.Response('{"status": "ok"}', 200);
      });

      final api = ApiClient(config: authConfig, httpClient: mockClient);
      await api.isHealthy();
      expect(capturedHeaders, isNotNull);
      expect(capturedHeaders!['Authorization'], 'Bearer test-token');
    });

    test('does not send Authorization header when no token', () async {
      Map<String, String>? capturedHeaders;
      final mockClient = MockClient((request) async {
        capturedHeaders = request.headers;
        return http.Response('{"status": "ok"}', 200);
      });

      final api = ApiClient(config: testConfig, httpClient: mockClient);
      await api.isHealthy();
      expect(capturedHeaders!.containsKey('Authorization'), false);
    });
  });

  group('ApiClient.getStreamUrl', () {
    test('returns stream URL without camera ID', () {
      final api = ApiClient(
        config: testConfig,
        httpClient: MockClient((_) async => http.Response('', 200)),
      );
      expect(api.getStreamUrl(), 'http://127.0.0.1:8090/stream');
    });

    test('returns stream URL with camera ID', () {
      final api = ApiClient(
        config: testConfig,
        httpClient: MockClient((_) async => http.Response('', 200)),
      );
      expect(
        api.getStreamUrl(cameraId: 'usb:0'),
        'http://127.0.0.1:8090/stream?camera_id=usb:0',
      );
    });
  });

  group('ApiException', () {
    test('toString includes message', () {
      const ex = ApiException('something failed', statusCode: 500);
      expect(ex.toString(), 'ApiException: something failed');
      expect(ex.statusCode, 500);
    });

    test('statusCode is optional', () {
      const ex = ApiException('network error');
      expect(ex.statusCode, isNull);
    });
  });
}
