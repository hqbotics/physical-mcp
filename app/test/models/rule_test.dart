import 'package:flutter_test/flutter_test.dart';
import 'package:physical_mcp_app/models/rule.dart';

void main() {
  group('WatchRule', () {
    test('constructs with required fields and defaults', () {
      final rule = WatchRule(
        id: 'r_abc123',
        name: 'Front door watch',
        condition: 'person at door',
        createdAt: DateTime(2026, 2, 20),
      );
      expect(rule.id, 'r_abc123');
      expect(rule.name, 'Front door watch');
      expect(rule.condition, 'person at door');
      expect(rule.cameraId, isNull);
      expect(rule.priority, 'medium'); // default
      expect(rule.notificationType, 'local'); // default
      expect(rule.cooldownSeconds, 60); // default
      expect(rule.enabled, true); // default
      expect(rule.triggerCount, 0); // default
      expect(rule.lastTriggered, isNull);
    });

    test('fromJson with all fields', () {
      final rule = WatchRule.fromJson({
        'id': 'r_xyz789',
        'name': 'Package delivery',
        'condition': 'package left at door',
        'camera_id': 'usb:0',
        'priority': 'high',
        'notification_type': 'desktop',
        'cooldown_seconds': 120,
        'enabled': true,
        'trigger_count': 5,
        'last_triggered': '2026-02-20T14:00:00',
        'created_at': '2026-02-19T10:00:00',
      });

      expect(rule.id, 'r_xyz789');
      expect(rule.name, 'Package delivery');
      expect(rule.condition, 'package left at door');
      expect(rule.cameraId, 'usb:0');
      expect(rule.priority, 'high');
      expect(rule.notificationType, 'desktop');
      expect(rule.cooldownSeconds, 120);
      expect(rule.enabled, true);
      expect(rule.triggerCount, 5);
      expect(rule.lastTriggered, isNotNull);
      expect(rule.createdAt.year, 2026);
    });

    test('fromJson with minimal fields (defaults)', () {
      final rule = WatchRule.fromJson({});
      expect(rule.id, '');
      expect(rule.name, 'Unnamed Rule');
      expect(rule.condition, '');
      expect(rule.priority, 'medium');
      expect(rule.notificationType, 'local');
      expect(rule.cooldownSeconds, 60);
      expect(rule.enabled, true);
      expect(rule.triggerCount, 0);
    });

    test('copyWith changes specific fields', () {
      final original = WatchRule(
        id: 'r_1',
        name: 'Original',
        condition: 'test condition',
        priority: 'low',
        enabled: true,
        createdAt: DateTime(2026, 2, 20),
      );

      final updated = original.copyWith(
        name: 'Updated',
        priority: 'high',
        enabled: false,
      );

      expect(updated.id, 'r_1'); // unchanged
      expect(updated.name, 'Updated');
      expect(updated.condition, 'test condition'); // unchanged
      expect(updated.priority, 'high');
      expect(updated.enabled, false);
      expect(updated.createdAt, original.createdAt); // unchanged
    });

    test('toJson produces correct keys', () {
      final rule = WatchRule(
        id: 'r_1',
        name: 'Test Rule',
        condition: 'something happens',
        cameraId: 'usb:0',
        priority: 'critical',
        notificationType: 'ntfy',
        cooldownSeconds: 300,
        createdAt: DateTime(2026, 2, 20),
      );
      final json = rule.toJson();

      expect(json['name'], 'Test Rule');
      expect(json['condition'], 'something happens');
      expect(json['camera_id'], 'usb:0');
      expect(json['priority'], 'critical');
      expect(json['notification_type'], 'ntfy');
      expect(json['cooldown_seconds'], 300);
      // toJson doesn't include id, enabled, trigger_count, etc. (create payload)
      expect(json.containsKey('id'), false);
    });

    test('fromJson handles null last_triggered', () {
      final rule = WatchRule.fromJson({
        'id': 'r_1',
        'name': 'Test',
        'condition': 'test',
        'last_triggered': null,
      });
      expect(rule.lastTriggered, isNull);
    });
  });

  group('AlertEvent', () {
    test('fromJson with all fields', () {
      final alert = AlertEvent.fromJson({
        'id': 'a_001',
        'rule_id': 'r_abc',
        'rule_name': 'Door watch',
        'camera_id': 'usb:0',
        'priority': 'high',
        'reasoning': 'Person detected at front door',
        'confidence': 0.92,
        'timestamp': '2026-02-20T12:00:00',
        'thumbnail_url': 'http://localhost:8090/frame?t=123',
      });

      expect(alert.id, 'a_001');
      expect(alert.ruleId, 'r_abc');
      expect(alert.ruleName, 'Door watch');
      expect(alert.cameraId, 'usb:0');
      expect(alert.priority, 'high');
      expect(alert.reasoning, 'Person detected at front door');
      expect(alert.confidence, 0.92);
      expect(alert.timestamp.year, 2026);
      expect(alert.thumbnailUrl, contains('frame'));
    });

    test('fromJson with minimal fields (defaults)', () {
      final alert = AlertEvent.fromJson({});
      expect(alert.id, '');
      expect(alert.ruleId, '');
      expect(alert.ruleName, '');
      expect(alert.cameraId, isNull);
      expect(alert.priority, 'medium');
      expect(alert.reasoning, '');
      expect(alert.confidence, 0.0);
      expect(alert.thumbnailUrl, isNull);
    });

    test('fromJson handles integer confidence', () {
      final alert = AlertEvent.fromJson({
        'id': 'a_1',
        'rule_id': 'r_1',
        'rule_name': 'Test',
        'priority': 'low',
        'reasoning': 'nothing',
        'confidence': 1,
        'timestamp': '2026-02-20T10:00:00',
      });
      expect(alert.confidence, 1.0);
      expect(alert.confidence, isA<double>());
    });

    test('fromJson handles missing timestamp', () {
      final alert = AlertEvent.fromJson({
        'id': 'a_1',
        'rule_id': 'r_1',
        'rule_name': 'Test',
        'priority': 'low',
        'reasoning': 'test',
        'confidence': 0.5,
      });
      // Should default to DateTime.now() — just check it's not null and recent
      expect(alert.timestamp, isNotNull);
      expect(alert.timestamp.year, greaterThanOrEqualTo(2026));
    });
  });
}
