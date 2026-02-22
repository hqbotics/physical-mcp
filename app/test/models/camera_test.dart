import 'package:flutter_test/flutter_test.dart';
import 'package:physical_mcp_app/models/camera.dart';

void main() {
  group('Camera', () {
    test('constructs with required fields and defaults', () {
      const camera = Camera(id: 'usb:0', name: 'Front Door', type: 'usb');
      expect(camera.id, 'usb:0');
      expect(camera.name, 'Front Door');
      expect(camera.type, 'usb');
      expect(camera.width, isNull);
      expect(camera.height, isNull);
      expect(camera.enabled, true); // default
      expect(camera.scene, isNull);
    });

    test('constructs with all fields', () {
      const camera = Camera(
        id: 'rtsp:1',
        name: 'Backyard',
        type: 'rtsp',
        width: 1920,
        height: 1080,
        enabled: false,
      );
      expect(camera.width, 1920);
      expect(camera.height, 1080);
      expect(camera.enabled, false);
    });

    test('displayResolution with dimensions', () {
      const camera = Camera(
        id: 'usb:0', name: 'Cam', type: 'usb',
        width: 1280, height: 720,
      );
      expect(camera.displayResolution, '1280x720');
    });

    test('displayResolution unknown when no dimensions', () {
      const camera = Camera(id: 'usb:0', name: 'Cam', type: 'usb');
      expect(camera.displayResolution, 'Unknown');
    });

    test('typeIcon for known types', () {
      expect(
        const Camera(id: '1', name: 'A', type: 'usb').typeIcon,
        'videocam',
      );
      expect(
        const Camera(id: '2', name: 'B', type: 'rtsp').typeIcon,
        'wifi',
      );
      expect(
        const Camera(id: '3', name: 'C', type: 'http').typeIcon,
        'language',
      );
    });

    test('typeIcon for unknown type', () {
      const camera = Camera(id: '1', name: 'A', type: 'custom');
      expect(camera.typeIcon, 'camera');
    });

    test('fromJson with all fields', () {
      final camera = Camera.fromJson({
        'id': 'usb:0',
        'name': 'Kitchen',
        'type': 'usb',
        'width': 640,
        'height': 480,
        'enabled': true,
        'scene': {
          'summary': 'A kitchen with dishes',
          'objects': ['plate', 'cup'],
          'people_count': 1,
          'change_score': 0.42,
          'timestamp': '2026-02-20T10:00:00',
        },
      });

      expect(camera.id, 'usb:0');
      expect(camera.name, 'Kitchen');
      expect(camera.type, 'usb');
      expect(camera.width, 640);
      expect(camera.height, 480);
      expect(camera.enabled, true);
      expect(camera.scene, isNotNull);
      expect(camera.scene!.summary, 'A kitchen with dishes');
      expect(camera.scene!.objects, ['plate', 'cup']);
      expect(camera.scene!.peopleCount, 1);
    });

    test('fromJson with minimal fields (defaults)', () {
      final camera = Camera.fromJson({});
      expect(camera.id, 'unknown');
      expect(camera.name, 'Camera');
      expect(camera.type, 'usb');
      expect(camera.enabled, true);
      expect(camera.scene, isNull);
    });

    test('copyWith changes specific fields', () {
      const original = Camera(id: 'usb:0', name: 'Old', type: 'usb', enabled: true);
      final updated = original.copyWith(name: 'New', enabled: false);

      expect(updated.id, 'usb:0'); // unchanged
      expect(updated.name, 'New');
      expect(updated.type, 'usb'); // unchanged
      expect(updated.enabled, false);
    });

    test('copyWith with scene', () {
      const original = Camera(id: 'usb:0', name: 'Cam', type: 'usb');
      const newScene = SceneState(summary: 'Living room');
      final updated = original.copyWith(scene: newScene);

      expect(updated.scene, isNotNull);
      expect(updated.scene!.summary, 'Living room');
    });
  });

  group('SceneState', () {
    test('constructs with required fields and defaults', () {
      const scene = SceneState(summary: 'An empty room');
      expect(scene.summary, 'An empty room');
      expect(scene.objects, isEmpty);
      expect(scene.peopleCount, isNull);
      expect(scene.changeScore, isNull);
      expect(scene.timestamp, isNull);
    });

    test('fromJson with all fields', () {
      final scene = SceneState.fromJson({
        'summary': 'Office with desk and monitor',
        'objects': ['desk', 'monitor', 'chair'],
        'people_count': 2,
        'change_score': 0.75,
        'timestamp': '2026-02-20T15:30:00',
      });

      expect(scene.summary, 'Office with desk and monitor');
      expect(scene.objects, ['desk', 'monitor', 'chair']);
      expect(scene.peopleCount, 2);
      expect(scene.changeScore, 0.75);
      expect(scene.timestamp, isNotNull);
      expect(scene.timestamp!.year, 2026);
    });

    test('fromJson with empty/minimal data', () {
      final scene = SceneState.fromJson({});
      expect(scene.summary, '');
      expect(scene.objects, isEmpty);
      expect(scene.peopleCount, isNull);
    });

    test('toJson round-trip', () {
      final original = SceneState(
        summary: 'Test scene',
        objects: ['lamp', 'table'],
        peopleCount: 3,
        changeScore: 0.5,
        timestamp: DateTime(2026, 2, 20, 12, 0),
      );
      final json = original.toJson();
      final restored = SceneState.fromJson(json);

      expect(restored.summary, original.summary);
      expect(restored.objects, original.objects);
      expect(restored.peopleCount, original.peopleCount);
      expect(restored.changeScore, original.changeScore);
    });

    test('fromJson handles integer change_score as double', () {
      final scene = SceneState.fromJson({
        'summary': 'test',
        'change_score': 1,
      });
      expect(scene.changeScore, 1.0);
      expect(scene.changeScore, isA<double>());
    });
  });
}
