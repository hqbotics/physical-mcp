import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/camera.dart';
import '../models/rule.dart';
import '../models/server_config.dart';

/// HTTP client for the physical-mcp Vision API.
///
/// Wraps all backend endpoints for the Flutter app.
class ApiClient {
  final ServerConfig config;
  final http.Client _http;

  ApiClient({required this.config, http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  void dispose() => _http.close();

  // ── Health ────────────────────────────────────────────────

  /// Check if the backend is reachable.
  Future<bool> isHealthy() async {
    try {
      final response = await _http
          .get(
            Uri.parse('${config.baseUrl}/health'),
            headers: config.headers,
          )
          .timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (e) {
      debugPrint('[ApiClient] Health check failed for ${config.baseUrl}: $e');
      return false;
    }
  }

  /// Get server health data.
  Future<Map<String, dynamic>> getHealth() async {
    final response = await _get('/health');
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  // ── Cameras ───────────────────────────────────────────────

  /// List all cameras.
  Future<List<Camera>> getCameras() async {
    final response = await _get('/cameras');
    final data = jsonDecode(response.body);
    if (data is List) {
      return data
          .map((e) => Camera.fromJson(e as Map<String, dynamic>))
          .toList();
    }
    return [];
  }

  // ── Scene ─────────────────────────────────────────────────

  /// Get current scene state.
  Future<SceneState> getScene() async {
    final response = await _get('/scene');
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return SceneState.fromJson(data);
  }

  /// Get a single JPEG frame.
  Future<List<int>> getFrame({String? cameraId}) async {
    final uri = cameraId != null
        ? '${config.baseUrl}/frame?camera_id=$cameraId'
        : '${config.baseUrl}/frame';
    final response = await _http.get(
      Uri.parse(uri),
      headers: config.headers,
    );
    if (response.statusCode != 200) {
      throw ApiException('Failed to get frame: ${response.statusCode}');
    }
    return response.bodyBytes;
  }

  /// Get the MJPEG stream URL.
  String getStreamUrl({String? cameraId}) {
    if (cameraId != null) {
      return '${config.baseUrl}/stream?camera_id=$cameraId';
    }
    return config.streamUrl;
  }

  /// Open all configured cameras on demand.
  ///
  /// In stdio mode, cameras are lazy-loaded. This triggers the backend
  /// to open cameras so they're available for the Flutter app.
  /// Returns the number of cameras opened.
  Future<int> openCameras() async {
    final response = await _post('/cameras/open');
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return data['count'] as int? ?? 0;
  }

  // ── Rules ─────────────────────────────────────────────────

  /// List all watch rules.
  Future<List<WatchRule>> getRules() async {
    final response = await _get('/rules');
    final data = jsonDecode(response.body);
    if (data is List) {
      return data
          .map((e) => WatchRule.fromJson(e as Map<String, dynamic>))
          .toList();
    }
    return [];
  }

  /// Create a new watch rule.
  Future<WatchRule> createRule({
    required String name,
    required String condition,
    String? cameraId,
    String priority = 'medium',
    String notificationType = 'local',
    int cooldownSeconds = 60,
  }) async {
    final response = await _post('/rules', body: {
      'name': name,
      'condition': condition,
      'camera_id': cameraId,
      'priority': priority,
      'notification_type': notificationType,
      'cooldown_seconds': cooldownSeconds,
    });
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return WatchRule.fromJson(data);
  }

  /// Delete a watch rule.
  Future<void> deleteRule(String ruleId) async {
    await _delete('/rules/$ruleId');
  }

  /// Toggle a watch rule on/off.
  Future<WatchRule> toggleRule(String ruleId) async {
    final response = await _put('/rules/$ruleId/toggle');
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return WatchRule.fromJson(data);
  }

  // ── Alerts ────────────────────────────────────────────────

  /// Get alert history.
  Future<List<AlertEvent>> getAlerts({int limit = 50}) async {
    final response = await _get('/alerts?limit=$limit');
    final data = jsonDecode(response.body);
    if (data is List) {
      return data
          .map((e) => AlertEvent.fromJson(e as Map<String, dynamic>))
          .toList();
    }
    return [];
  }

  // ── System ──────────────────────────────────────────────

  /// Get system stats including provider info.
  Future<Map<String, dynamic>> getSystemStats() async {
    final response = await _get('/health');
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// Configure the vision AI provider.
  Future<Map<String, dynamic>> configureProvider({
    required String provider,
    required String apiKey,
    String? model,
    String? baseUrl,
  }) async {
    final response = await _post('/configure_provider', body: {
      'provider': provider,
      'api_key': apiKey,
      'model': ?model,
      'base_url': ?baseUrl,
    });
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  // ── Internals ─────────────────────────────────────────────

  Future<http.Response> _get(String path) async {
    final response = await _http
        .get(
          Uri.parse('${config.baseUrl}$path'),
          headers: config.headers,
        )
        .timeout(const Duration(seconds: 10));
    _checkResponse(response);
    return response;
  }

  Future<http.Response> _post(String path,
      {Map<String, dynamic>? body}) async {
    final response = await _http
        .post(
          Uri.parse('${config.baseUrl}$path'),
          headers: {
            ...config.headers,
            'Content-Type': 'application/json',
          },
          body: body != null ? jsonEncode(body) : null,
        )
        .timeout(const Duration(seconds: 10));
    _checkResponse(response);
    return response;
  }

  Future<http.Response> _put(String path, {Map<String, dynamic>? body}) async {
    final response = await _http
        .put(
          Uri.parse('${config.baseUrl}$path'),
          headers: {
            ...config.headers,
            'Content-Type': 'application/json',
          },
          body: body != null ? jsonEncode(body) : null,
        )
        .timeout(const Duration(seconds: 10));
    _checkResponse(response);
    return response;
  }

  Future<http.Response> _delete(String path) async {
    final response = await _http
        .delete(
          Uri.parse('${config.baseUrl}$path'),
          headers: config.headers,
        )
        .timeout(const Duration(seconds: 10));
    _checkResponse(response);
    return response;
  }

  void _checkResponse(http.Response response) {
    if (response.statusCode >= 400) {
      throw ApiException(
        'API error ${response.statusCode}: ${response.body}',
        statusCode: response.statusCode,
      );
    }
  }
}

/// API exception with optional status code.
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  const ApiException(this.message, {this.statusCode});

  @override
  String toString() => 'ApiException: $message';
}
