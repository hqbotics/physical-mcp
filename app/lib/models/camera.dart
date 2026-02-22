/// Camera model — represents a single camera source on the backend.
class Camera {
  final String id;
  final String name;
  final String type; // 'usb', 'rtsp', 'http'
  final int? width;
  final int? height;
  final bool enabled;
  final SceneState? scene;

  const Camera({
    required this.id,
    required this.name,
    required this.type,
    this.width,
    this.height,
    this.enabled = true,
    this.scene,
  });

  String get displayResolution {
    if (width != null && height != null) return '${width}x$height';
    return 'Unknown';
  }

  String get typeIcon {
    switch (type) {
      case 'usb':
        return 'videocam';
      case 'rtsp':
        return 'wifi';
      case 'http':
        return 'language';
      default:
        return 'camera';
    }
  }

  Camera copyWith({
    String? name,
    SceneState? scene,
    bool? enabled,
  }) {
    return Camera(
      id: id,
      name: name ?? this.name,
      type: type,
      width: width,
      height: height,
      enabled: enabled ?? this.enabled,
      scene: scene ?? this.scene,
    );
  }

  factory Camera.fromJson(Map<String, dynamic> json) {
    return Camera(
      id: json['id'] as String? ?? 'unknown',
      name: json['name'] as String? ?? 'Camera',
      type: json['type'] as String? ?? 'usb',
      width: json['width'] as int?,
      height: json['height'] as int?,
      enabled: json['enabled'] as bool? ?? true,
      scene: json['scene'] != null
          ? SceneState.fromJson(json['scene'] as Map<String, dynamic>)
          : null,
    );
  }
}

/// Current scene state for a camera.
class SceneState {
  final String summary;
  final List<String> objects;
  final int? peopleCount;
  final double? changeScore;
  final DateTime? timestamp;

  const SceneState({
    required this.summary,
    this.objects = const [],
    this.peopleCount,
    this.changeScore,
    this.timestamp,
  });

  factory SceneState.fromJson(Map<String, dynamic> json) {
    return SceneState(
      summary: json['summary'] as String? ?? '',
      objects: (json['objects'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      peopleCount: json['people_count'] as int?,
      changeScore: (json['change_score'] as num?)?.toDouble(),
      timestamp: json['timestamp'] != null
          ? DateTime.tryParse(json['timestamp'] as String)
          : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'summary': summary,
        'objects': objects,
        'people_count': peopleCount,
        'change_score': changeScore,
        'timestamp': timestamp?.toIso8601String(),
      };
}
