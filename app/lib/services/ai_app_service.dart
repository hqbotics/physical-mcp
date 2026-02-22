import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// Status of an AI app's connection to Physical MCP.
enum AIAppStatus {
  /// App not installed on this machine.
  notInstalled,

  /// App installed but Physical MCP not configured.
  notConfigured,

  /// Physical MCP is configured in the app's config.
  configured,

  /// HTTP-only app (e.g. ChatGPT) — requires manual setup.
  manualSetup,
}

/// Info about a supported AI chat application.
class AIAppInfo {
  final String name;
  final String transport; // "stdio" | "http"
  final String? configPath;
  final String serverKey; // "mcpServers" or "servers"
  final String description;
  final String setupHint;
  AIAppStatus status;

  AIAppInfo({
    required this.name,
    required this.transport,
    this.configPath,
    this.serverKey = 'mcpServers',
    this.description = '',
    this.setupHint = '',
    this.status = AIAppStatus.notInstalled,
  });
}

/// Service for detecting and configuring AI chat apps.
///
/// Mirrors the logic in `src/physical_mcp/ai_apps.py`:
/// - Detects installed AI apps by checking config directories
/// - Writes MCP server entries to their JSON config files
/// - Returns status for each known app
class AIAppService {
  static const String _mcpEntryKey = 'physical-mcp';

  /// Get the LAN IP address from the backend health endpoint.
  static Future<String> getLanIp(int port) async {
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLinkLocal: false,
      );
      for (final iface in interfaces) {
        for (final addr in iface.addresses) {
          if (!addr.isLoopback && addr.address.startsWith('192.168')) {
            return addr.address;
          }
        }
      }
      // Fallback: first non-loopback
      for (final iface in interfaces) {
        for (final addr in iface.addresses) {
          if (!addr.isLoopback) return addr.address;
        }
      }
    } catch (_) {}
    return '127.0.0.1';
  }

  /// Build the known apps list with macOS paths.
  static List<AIAppInfo> _knownApps() {
    final home = Platform.environment['HOME'] ?? '/Users/unknown';
    return [
      AIAppInfo(
        name: 'Claude Desktop',
        transport: 'stdio',
        configPath: '$home/Library/Application Support/Claude/claude_desktop_config.json',
        serverKey: 'mcpServers',
        description: 'Anthropic\'s AI assistant',
        setupHint: 'Restart Claude Desktop after configuring.',
      ),
      AIAppInfo(
        name: 'ChatGPT',
        transport: 'http',
        description: 'OpenAI\'s AI assistant',
        setupHint: 'Settings \u2192 Connectors \u2192 Add MCP Server',
      ),
      AIAppInfo(
        name: 'Cursor',
        transport: 'stdio',
        configPath: '$home/.cursor/mcp.json',
        serverKey: 'mcpServers',
        description: 'AI-powered code editor',
        setupHint: 'Restart Cursor after configuring.',
      ),
      AIAppInfo(
        name: 'VS Code',
        transport: 'stdio',
        configPath: '$home/Library/Application Support/Code/User/mcp.json',
        serverKey: 'servers',
        description: 'Microsoft\'s code editor with Copilot',
        setupHint: 'Restart VS Code after configuring.',
      ),
      AIAppInfo(
        name: 'Windsurf',
        transport: 'stdio',
        configPath: '$home/.codeium/windsurf/mcp_config.json',
        serverKey: 'mcpServers',
        description: 'Codeium\'s AI code editor',
        setupHint: 'Restart Windsurf after configuring.',
      ),
      AIAppInfo(
        name: 'Gemini',
        transport: 'stdio',
        configPath: '$home/Library/Application Support/Google/Gemini/settings.json',
        serverKey: 'mcpServers',
        description: 'Google\'s AI assistant',
        setupHint: 'Restart Gemini after configuring.',
      ),
    ];
  }

  /// Build the MCP server JSON entry for physical-mcp.
  static Map<String, dynamic> _buildMcpEntry() {
    // Check if uv is available
    final uvPath = _findExecutable('uv');
    if (uvPath != null) {
      return {
        'command': uvPath,
        'args': ['run', 'physical-mcp'],
      };
    }
    // Fallback to direct command
    return {'command': 'physical-mcp'};
  }

  /// Find an executable on PATH.
  static String? _findExecutable(String name) {
    try {
      final result = Process.runSync('which', [name]);
      if (result.exitCode == 0) {
        return (result.stdout as String).trim();
      }
    } catch (_) {}
    // Common locations
    final commonPaths = [
      '/opt/homebrew/bin/$name',
      '/usr/local/bin/$name',
      '${Platform.environment['HOME']}/.local/bin/$name',
    ];
    for (final path in commonPaths) {
      if (File(path).existsSync()) return path;
    }
    return null;
  }

  /// Detect all known AI apps and their configuration status.
  static List<AIAppInfo> detectApps() {
    final apps = _knownApps();
    for (final app in apps) {
      if (app.transport == 'http') {
        app.status = AIAppStatus.manualSetup;
        continue;
      }
      if (app.configPath == null) {
        app.status = AIAppStatus.notInstalled;
        continue;
      }
      final configFile = File(app.configPath!);
      if (!configFile.parent.existsSync()) {
        app.status = AIAppStatus.notInstalled;
        continue;
      }
      // App is installed — check if configured
      if (!configFile.existsSync()) {
        app.status = AIAppStatus.notConfigured;
        continue;
      }
      try {
        final data = jsonDecode(configFile.readAsStringSync()) as Map<String, dynamic>;
        final servers = data[app.serverKey] as Map<String, dynamic>? ?? {};
        app.status = servers.containsKey(_mcpEntryKey)
            ? AIAppStatus.configured
            : AIAppStatus.notConfigured;
      } catch (_) {
        app.status = AIAppStatus.notConfigured;
      }
    }
    return apps;
  }

  /// Configure Physical MCP in an AI app's config file.
  /// Returns true on success.
  static Future<bool> configureApp(AIAppInfo app) async {
    if (app.transport == 'http' || app.configPath == null) {
      return false;
    }
    try {
      final configFile = File(app.configPath!);

      // Read existing config
      Map<String, dynamic> config = {};
      if (configFile.existsSync()) {
        try {
          config = jsonDecode(configFile.readAsStringSync()) as Map<String, dynamic>;
        } catch (_) {
          config = {};
        }
        // Create backup
        final backup = File('${app.configPath}.bak');
        configFile.copySync(backup.path);
      }

      // Add our entry
      final servers = (config[app.serverKey] as Map<String, dynamic>?) ?? {};
      servers[_mcpEntryKey] = _buildMcpEntry();
      config[app.serverKey] = servers;

      // Write back
      configFile.parent.createSync(recursive: true);
      configFile.writeAsStringSync(
        '${const JsonEncoder.withIndent('  ').convert(config)}\n',
      );

      app.status = AIAppStatus.configured;
      debugPrint('[AIAppService] Configured ${app.name} at ${app.configPath}');
      return true;
    } catch (e) {
      debugPrint('[AIAppService] Failed to configure ${app.name}: $e');
      return false;
    }
  }

  /// Check if any AI app is configured.
  static bool hasAnyConfigured(List<AIAppInfo> apps) {
    return apps.any((a) => a.status == AIAppStatus.configured);
  }
}
