/// Connection configuration for a physical-mcp backend server.
class ServerConfig {
  final String name;
  final String host;
  final int port;
  final String? authToken;
  final bool isDiscovered; // true if found via mDNS

  const ServerConfig({
    required this.name,
    required this.host,
    this.port = 8090,
    this.authToken,
    this.isDiscovered = false,
  });

  String get baseUrl => 'http://$host:$port';
  String get streamUrl => '$baseUrl/stream';
  String get frameUrl => '$baseUrl/frame';

  Map<String, String> get headers => {
        if (authToken != null && authToken!.isNotEmpty)
          'Authorization': 'Bearer $authToken',
      };

  ServerConfig copyWith({
    String? name,
    String? host,
    int? port,
    String? authToken,
    bool? isDiscovered,
  }) {
    return ServerConfig(
      name: name ?? this.name,
      host: host ?? this.host,
      port: port ?? this.port,
      authToken: authToken ?? this.authToken,
      isDiscovered: isDiscovered ?? this.isDiscovered,
    );
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'host': host,
        'port': port,
        'authToken': authToken,
        'isDiscovered': isDiscovered,
      };

  factory ServerConfig.fromJson(Map<String, dynamic> json) {
    return ServerConfig(
      name: json['name'] as String? ?? 'Unknown',
      host: json['host'] as String,
      port: json['port'] as int? ?? 8090,
      authToken: json['authToken'] as String?,
      isDiscovered: json['isDiscovered'] as bool? ?? false,
    );
  }

  @override
  String toString() => 'ServerConfig($name @ $host:$port)';

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is ServerConfig && host == other.host && port == other.port;

  @override
  int get hashCode => host.hashCode ^ port.hashCode;
}
