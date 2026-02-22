import 'package:flutter_test/flutter_test.dart';
import 'package:physical_mcp_app/models/server_config.dart';

void main() {
  group('ServerConfig', () {
    test('constructs with required fields and defaults', () {
      const config = ServerConfig(name: 'Test', host: '192.168.1.10');
      expect(config.name, 'Test');
      expect(config.host, '192.168.1.10');
      expect(config.port, 8090); // default
      expect(config.authToken, isNull);
      expect(config.isDiscovered, false);
    });

    test('constructs with all fields', () {
      const config = ServerConfig(
        name: 'My Server',
        host: '10.0.0.5',
        port: 9090,
        authToken: 'secret-token',
        isDiscovered: true,
      );
      expect(config.name, 'My Server');
      expect(config.host, '10.0.0.5');
      expect(config.port, 9090);
      expect(config.authToken, 'secret-token');
      expect(config.isDiscovered, true);
    });

    test('baseUrl formats correctly', () {
      const config = ServerConfig(name: 'Test', host: '192.168.1.10', port: 8090);
      expect(config.baseUrl, 'http://192.168.1.10:8090');
    });

    test('baseUrl with non-default port', () {
      const config = ServerConfig(name: 'Test', host: 'localhost', port: 3000);
      expect(config.baseUrl, 'http://localhost:3000');
    });

    test('streamUrl appends /stream', () {
      const config = ServerConfig(name: 'Test', host: '127.0.0.1', port: 8090);
      expect(config.streamUrl, 'http://127.0.0.1:8090/stream');
    });

    test('frameUrl appends /frame', () {
      const config = ServerConfig(name: 'Test', host: '127.0.0.1', port: 8090);
      expect(config.frameUrl, 'http://127.0.0.1:8090/frame');
    });

    test('headers empty when no auth token', () {
      const config = ServerConfig(name: 'Test', host: 'localhost');
      expect(config.headers, isEmpty);
    });

    test('headers empty when auth token is empty string', () {
      const config = ServerConfig(name: 'Test', host: 'localhost', authToken: '');
      expect(config.headers, isEmpty);
    });

    test('headers contain Authorization when auth token present', () {
      const config = ServerConfig(
        name: 'Test',
        host: 'localhost',
        authToken: 'my-secret',
      );
      expect(config.headers, {'Authorization': 'Bearer my-secret'});
    });

    test('toJson round-trip', () {
      const original = ServerConfig(
        name: 'My Server',
        host: '10.0.0.5',
        port: 9090,
        authToken: 'tok123',
        isDiscovered: true,
      );
      final json = original.toJson();
      final restored = ServerConfig.fromJson(json);

      expect(restored.name, original.name);
      expect(restored.host, original.host);
      expect(restored.port, original.port);
      expect(restored.authToken, original.authToken);
      expect(restored.isDiscovered, original.isDiscovered);
    });

    test('fromJson with minimal fields', () {
      final config = ServerConfig.fromJson({'host': '192.168.1.1'});
      expect(config.host, '192.168.1.1');
      expect(config.name, 'Unknown'); // default
      expect(config.port, 8090); // default
      expect(config.authToken, isNull);
      expect(config.isDiscovered, false);
    });

    test('copyWith changes specific fields', () {
      const original = ServerConfig(
        name: 'Original',
        host: '10.0.0.1',
        port: 8090,
      );
      final copy = original.copyWith(name: 'Updated', port: 9090);

      expect(copy.name, 'Updated');
      expect(copy.host, '10.0.0.1'); // unchanged
      expect(copy.port, 9090);
    });

    test('equality based on host and port', () {
      const a = ServerConfig(name: 'A', host: '10.0.0.1', port: 8090);
      const b = ServerConfig(name: 'B', host: '10.0.0.1', port: 8090);
      const c = ServerConfig(name: 'A', host: '10.0.0.2', port: 8090);

      expect(a, equals(b)); // same host:port
      expect(a, isNot(equals(c))); // different host
    });

    test('hashCode consistent with equality', () {
      const a = ServerConfig(name: 'A', host: '10.0.0.1', port: 8090);
      const b = ServerConfig(name: 'B', host: '10.0.0.1', port: 8090);
      expect(a.hashCode, equals(b.hashCode));
    });

    test('toString includes name, host, port', () {
      const config = ServerConfig(name: 'My Server', host: '10.0.0.1', port: 8090);
      expect(config.toString(), contains('My Server'));
      expect(config.toString(), contains('10.0.0.1'));
      expect(config.toString(), contains('8090'));
    });
  });
}
