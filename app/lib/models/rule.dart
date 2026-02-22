/// Watch rule model — represents an AI monitoring rule.
class WatchRule {
  final String id;
  final String name;
  final String condition;
  final String? cameraId;
  final String priority; // 'low', 'medium', 'high', 'critical'
  final String notificationType; // 'local', 'desktop', 'ntfy'
  final int cooldownSeconds;
  final bool enabled;
  final int triggerCount;
  final DateTime? lastTriggered;
  final DateTime createdAt;

  const WatchRule({
    required this.id,
    required this.name,
    required this.condition,
    this.cameraId,
    this.priority = 'medium',
    this.notificationType = 'local',
    this.cooldownSeconds = 60,
    this.enabled = true,
    this.triggerCount = 0,
    this.lastTriggered,
    required this.createdAt,
  });

  WatchRule copyWith({
    String? name,
    String? condition,
    String? cameraId,
    String? priority,
    String? notificationType,
    int? cooldownSeconds,
    bool? enabled,
  }) {
    return WatchRule(
      id: id,
      name: name ?? this.name,
      condition: condition ?? this.condition,
      cameraId: cameraId ?? this.cameraId,
      priority: priority ?? this.priority,
      notificationType: notificationType ?? this.notificationType,
      cooldownSeconds: cooldownSeconds ?? this.cooldownSeconds,
      enabled: enabled ?? this.enabled,
      triggerCount: triggerCount,
      lastTriggered: lastTriggered,
      createdAt: createdAt,
    );
  }

  factory WatchRule.fromJson(Map<String, dynamic> json) {
    return WatchRule(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? 'Unnamed Rule',
      condition: json['condition'] as String? ?? '',
      cameraId: json['camera_id'] as String?,
      priority: json['priority'] as String? ?? 'medium',
      notificationType: json['notification_type'] as String? ?? 'local',
      cooldownSeconds: json['cooldown_seconds'] as int? ?? 60,
      enabled: json['enabled'] as bool? ?? true,
      triggerCount: json['trigger_count'] as int? ?? 0,
      lastTriggered: json['last_triggered'] != null
          ? DateTime.tryParse(json['last_triggered'] as String)
          : null,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'] as String) ?? DateTime.now()
          : DateTime.now(),
    );
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'condition': condition,
        'camera_id': cameraId,
        'priority': priority,
        'notification_type': notificationType,
        'cooldown_seconds': cooldownSeconds,
      };
}

/// Alert event — a triggered rule evaluation.
class AlertEvent {
  final String id;
  final String ruleId;
  final String ruleName;
  final String? cameraId;
  final String priority;
  final String reasoning;
  final double confidence;
  final DateTime timestamp;
  final String? thumbnailUrl;

  const AlertEvent({
    required this.id,
    required this.ruleId,
    required this.ruleName,
    this.cameraId,
    required this.priority,
    required this.reasoning,
    required this.confidence,
    required this.timestamp,
    this.thumbnailUrl,
  });

  factory AlertEvent.fromJson(Map<String, dynamic> json) {
    return AlertEvent(
      id: json['id'] as String? ?? '',
      ruleId: json['rule_id'] as String? ?? '',
      ruleName: json['rule_name'] as String? ?? '',
      cameraId: json['camera_id'] as String?,
      priority: json['priority'] as String? ?? 'medium',
      reasoning: json['reasoning'] as String? ?? '',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      timestamp: json['timestamp'] != null
          ? DateTime.tryParse(json['timestamp'] as String) ?? DateTime.now()
          : DateTime.now(),
      thumbnailUrl: json['thumbnail_url'] as String?,
    );
  }
}
