import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'models/camera.dart';
import 'models/rule.dart';
import 'models/server_config.dart';
import 'screens/alerts_screen.dart';
import 'screens/connect_ai_screen.dart';
import 'screens/connect_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/live_view_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/rules_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/splash_screen.dart';
import 'services/ai_app_service.dart';
import 'services/api_client.dart';
import 'services/backend_manager.dart';
import 'services/mdns_discovery.dart';
import 'services/sse_client.dart';
import 'services/tunnel_manager.dart';
import 'theme/dji_theme.dart';
import 'widgets/app_logo.dart';

void main() {
  runApp(const ProviderScope(child: PhysicalMCPApp()));
}

class PhysicalMCPApp extends StatelessWidget {
  const PhysicalMCPApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Physical MCP',
      debugShowCheckedModeBanner: false,
      theme: DJITheme.dark,
      home: const AppShell(),
    );
  }
}

/// Root shell that manages navigation between onboarding → splash → connect → main app.
class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  _AppState _state = _AppState.splash;
  ServerConfig? _serverConfig;
  ApiClient? _apiClient;
  final MdnsDiscovery _discovery = MdnsDiscovery();
  List<ServerConfig> _discoveredServers = [];
  bool _isScanning = false;

  // App data
  List<Camera> _cameras = [];
  List<WatchRule> _rules = [];
  List<AlertEvent> _alerts = [];
  bool _isLoading = false;
  bool _isConnected = false;
  bool _connectionLost = false;
  String? _filterPriority;
  bool _configLoaded = false;

  // AI Provider info
  String? _aiProvider;
  String? _aiModel;

  // Embedded backend manager — with state callback for cascade restart
  late final BackendManager _backendManager = BackendManager(
    port: 8090,
    onStateChanged: (state) {
      if (mounted) setState(() {});
      // If backend recovered from a crash, restart tunnel so it points
      // to the live backend (tunnel URL may change — consumer sees update).
      if (state == BackendState.running &&
          _tunnelManager.state != TunnelState.stopped) {
        debugPrint('[AppShell] Backend recovered — restarting tunnel...');
        _startTunnelWhenReady();
      }
    },
  );

  // Cloudflare Tunnel for ChatGPT HTTPS access — with reactive UI callback
  late final TunnelManager _tunnelManager = TunnelManager(
    onStateChanged: (state, url) {
      if (mounted) setState(() {}); // Auto-refresh UI on tunnel state change
    },
  );

  // SSE client for real-time alerts
  SseClient? _sseClient;

  // Health check timer
  Timer? _healthTimer;

  // Bottom nav
  int _currentTab = 0;

  // Connect AI banner
  bool _showAIBanner = false;
  bool _aiSetupDismissed = false;

  @override
  void initState() {
    super.initState();
    _initApp();
  }

  Future<void> _initApp() async {
    final prefs = await SharedPreferences.getInstance();
    final onboardingDone = prefs.getBool('onboarding_completed') ?? false;

    if (!onboardingDone) {
      setState(() => _state = _AppState.onboarding);
      return;
    }

    // If embedded backend exists, start it before connecting
    if (_backendManager.isEmbedded) {
      setState(() => _state = _AppState.starting);
      final started = await _backendManager.start();
      debugPrint('[AppShell] Embedded backend started: $started');
      // Proceed to splash regardless — splash will auto-discover localhost
    }

    await _loadSavedConfig();
    setState(() => _state = _AppState.splash);
  }

  @override
  void dispose() {
    _apiClient?.dispose();
    _discovery.dispose();
    _sseClient?.dispose();
    _healthTimer?.cancel();
    _tunnelManager.dispose();
    _backendManager.dispose();
    super.dispose();
  }

  // ── Config Persistence ──────────────────────────────────────

  Future<void> _loadSavedConfig() async {
    if (_configLoaded) return;
    final prefs = await SharedPreferences.getInstance();
    final configJson = prefs.getString('server_config');
    if (configJson != null) {
      try {
        final config = ServerConfig.fromJson(
            jsonDecode(configJson) as Map<String, dynamic>);
        _serverConfig = config;
        _apiClient = ApiClient(config: config);
        debugPrint('[AppShell] Loaded saved config: ${config.host}:${config.port}');
      } catch (e) {
        debugPrint('[AppShell] Invalid saved config: $e');
      }
    } else {
      debugPrint('[AppShell] No saved config found');
    }
    _configLoaded = true;
  }

  Future<void> _saveConfig(ServerConfig config) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_config', jsonEncode(config.toJson()));
  }

  // ── Discovery & Connection ──────────────────────────────────

  Future<bool> _checkSavedConnection() async {
    // Ensure saved config is loaded before checking
    await _loadSavedConfig();

    debugPrint('[AppShell] Checking connection... apiClient=${_apiClient != null}');

    // Try saved config first
    if (_apiClient != null) {
      debugPrint('[AppShell] Trying saved config: ${_serverConfig?.baseUrl}');
      final healthy = await _apiClient!.isHealthy();
      debugPrint('[AppShell] Saved config healthy: $healthy');
      if (healthy) {
        _isConnected = true;
        return true;
      }
    }

    // Try mDNS discovery
    debugPrint('[AppShell] Trying mDNS discovery...');
    setState(() => _isScanning = true);
    try {
      final servers = await _discovery.scan(
        timeout: const Duration(seconds: 4),
      );
      debugPrint('[AppShell] mDNS found ${servers.length} servers');
      setState(() {
        _discoveredServers = servers;
        _isScanning = false;
      });

      if (servers.isNotEmpty) {
        final config = servers.first;
        final client = ApiClient(config: config);
        final healthy = await client.isHealthy();
        if (healthy) {
          _serverConfig = config;
          _apiClient = client;
          _isConnected = true;
          await _saveConfig(config);
          return true;
        }
      }
    } catch (e) {
      debugPrint('[AppShell] mDNS discovery error: $e');
      setState(() => _isScanning = false);
    }

    // Try common local addresses as fallback (dev setup)
    debugPrint('[AppShell] Trying localhost fallbacks...');
    for (final host in ['127.0.0.1', 'localhost', '0.0.0.0']) {
      final localConfig = ServerConfig(
        name: 'Physical MCP (Local)',
        host: host,
        port: 8090,
      );
      final localClient = ApiClient(config: localConfig);
      debugPrint('[AppShell] Trying $host:8090...');
      final localHealthy = await localClient.isHealthy();
      debugPrint('[AppShell] $host:8090 healthy: $localHealthy');
      if (localHealthy) {
        _serverConfig = localConfig;
        _apiClient = localClient;
        _isConnected = true;
        await _saveConfig(localConfig);
        return true;
      }
    }

    debugPrint('[AppShell] All connection attempts failed');
    return false;
  }

  Future<void> _connectTo(ServerConfig config) async {
    setState(() => _isLoading = true);

    final client = ApiClient(config: config);
    final healthy = await client.isHealthy();

    if (healthy) {
      _serverConfig = config;
      _apiClient = client;
      _isConnected = true;
      await _saveConfig(config);
      await _loadData();
      _startHealthCheck();
      _connectSse();
      _fetchProviderInfo();
      setState(() {
        _state = _AppState.main;
        _isLoading = false;
      });
    } else {
      setState(() => _isLoading = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Cannot connect to ${config.host}:${config.port}'),
            backgroundColor: DJIColors.danger,
          ),
        );
      }
    }
  }

  Future<void> _rescan() async {
    setState(() => _isScanning = true);
    final servers = await _discovery.scan(
      timeout: const Duration(seconds: 5),
    );
    setState(() {
      _discoveredServers = servers;
      _isScanning = false;
    });
  }

  // ── Health Check ──────────────────────────────────────────────

  void _startHealthCheck() {
    _healthTimer?.cancel();
    _healthTimer = Timer.periodic(const Duration(seconds: 15), (_) async {
      if (_apiClient == null || _state != _AppState.main) return;
      final healthy = await _apiClient!.isHealthy();
      if (!mounted) return;

      if (!healthy && !_connectionLost) {
        setState(() => _connectionLost = true);
      } else if (healthy && _connectionLost) {
        setState(() {
          _connectionLost = false;
          _isConnected = true;
        });
        // Refresh data on reconnect
        _loadData();
      }
    });
  }

  // ── SSE Real-Time Updates ─────────────────────────────────────

  void _connectSse() {
    if (_serverConfig == null) return;
    _sseClient?.dispose();
    _sseClient = SseClient(config: _serverConfig!);
    _sseClient!.connect();
    _sseClient!.events.listen((event) {
      if (!mounted) return;
      if (event.type == 'alert' && event.json != null) {
        try {
          final alert = AlertEvent.fromJson(event.json!);
          setState(() => _alerts.insert(0, alert));
        } catch (e) {
          debugPrint('[SSE] Failed to parse alert: $e');
        }
      } else if (event.type == 'scene_update' && event.json != null) {
        // Update camera scene data in-place
        try {
          final data = event.json!;
          final cameraId = data['camera_id'] as String?;
          if (cameraId != null) {
            final idx = _cameras.indexWhere((c) => c.id == cameraId);
            if (idx >= 0 && data['scene'] != null) {
              final scene = SceneState.fromJson(
                  data['scene'] as Map<String, dynamic>);
              setState(() {
                _cameras[idx] = _cameras[idx].copyWith(scene: scene);
              });
            }
          }
        } catch (e) {
          debugPrint('[SSE] Failed to parse scene update: $e');
        }
      }
    });
  }

  // ── AI Provider Info ──────────────────────────────────────────

  Future<void> _fetchProviderInfo() async {
    if (_apiClient == null) return;
    try {
      final stats = await _apiClient!.getSystemStats();
      setState(() {
        _aiProvider = stats['provider'] as String?;
        _aiModel = stats['model'] as String?;
        if (_aiProvider == 'none') _aiProvider = null;
        if (_aiModel == 'none') _aiModel = null;
      });
    } catch (e) {
      debugPrint('[AppShell] Failed to fetch provider info: $e');
    }
  }

  Future<void> _showProviderConfigDialog() async {
    final providerController = TextEditingController(text: _aiProvider ?? '');
    final apiKeyController = TextEditingController();
    final modelController = TextEditingController(text: _aiModel ?? '');
    final baseUrlController = TextEditingController();

    String selectedProvider = _aiProvider ?? 'openai-compatible';

    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Configure AI Provider'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: selectedProvider,
                  decoration: const InputDecoration(labelText: 'Provider'),
                  items: const [
                    DropdownMenuItem(
                        value: 'anthropic', child: Text('Anthropic')),
                    DropdownMenuItem(
                        value: 'openai', child: Text('OpenAI')),
                    DropdownMenuItem(
                        value: 'google', child: Text('Google')),
                    DropdownMenuItem(
                        value: 'openai-compatible',
                        child: Text('OpenAI Compatible')),
                  ],
                  onChanged: (v) =>
                      setDialogState(() => selectedProvider = v!),
                ),
                const SizedBox(height: DJISpacing.md),
                TextField(
                  controller: apiKeyController,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'API Key',
                    hintText: 'Enter your API key',
                  ),
                ),
                const SizedBox(height: DJISpacing.md),
                TextField(
                  controller: modelController,
                  decoration: const InputDecoration(
                    labelText: 'Model (optional)',
                    hintText: 'e.g. gpt-4o, claude-3-haiku',
                  ),
                ),
                if (selectedProvider == 'openai-compatible') ...[
                  const SizedBox(height: DJISpacing.md),
                  TextField(
                    controller: baseUrlController,
                    decoration: const InputDecoration(
                      labelText: 'Base URL',
                      hintText: 'https://api.example.com/v1',
                    ),
                  ),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );

    if (result == true && _apiClient != null) {
      try {
        await _apiClient!.configureProvider(
          provider: selectedProvider,
          apiKey: apiKeyController.text.trim(),
          model: modelController.text.trim().isNotEmpty
              ? modelController.text.trim()
              : null,
          baseUrl: baseUrlController.text.trim().isNotEmpty
              ? baseUrlController.text.trim()
              : null,
        );
        await _fetchProviderInfo();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('AI provider configured'),
              backgroundColor: DJIColors.secondary,
            ),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Failed to configure: $e'),
              backgroundColor: DJIColors.danger,
            ),
          );
        }
      }
    }

    providerController.dispose();
    apiKeyController.dispose();
    modelController.dispose();
    baseUrlController.dispose();
  }

  // ── Data Loading ────────────────────────────────────────────

  Future<void> _loadData() async {
    if (_apiClient == null) {
      debugPrint('[AppShell] _loadData: apiClient is null, skipping');
      return;
    }
    debugPrint('[AppShell] _loadData: loading cameras, rules, alerts...');
    setState(() => _isLoading = true);

    try {
      final futures = await Future.wait([
        _apiClient!.getCameras(),
        _apiClient!.getRules(),
        _apiClient!.getAlerts(),
      ]);

      setState(() {
        _cameras = futures[0] as List<Camera>;
        _rules = futures[1] as List<WatchRule>;
        _alerts = futures[2] as List<AlertEvent>;
        _isLoading = false;
      });
      debugPrint('[AppShell] _loadData: loaded ${_cameras.length} cameras, ${_rules.length} rules, ${_alerts.length} alerts');

      // If no cameras found, try to open them on the backend.
      // In stdio mode, cameras are lazy-loaded. POST /cameras/open triggers opening.
      if (_cameras.isEmpty) {
        debugPrint('[AppShell] No cameras found, requesting backend to open cameras...');
        try {
          final count = await _apiClient!.openCameras();
          debugPrint('[AppShell] Backend opened $count cameras');
          if (count > 0) {
            // Re-fetch camera list after opening
            final cams = await _apiClient!.getCameras();
            setState(() => _cameras = cams);
            debugPrint('[AppShell] After open: ${_cameras.length} cameras available');
          }
        } catch (e) {
          debugPrint('[AppShell] openCameras failed: $e');
        }
      }
    } catch (e) {
      debugPrint('[AppShell] _loadData ERROR: $e');
      setState(() => _isLoading = false);
    }

    // Start tunnel for ChatGPT HTTPS access (if cameras detected).
    // Waits for MCP server to be ready first — prevents Cloudflare error pages.
    if (_cameras.isNotEmpty && _tunnelManager.state == TunnelState.stopped) {
      _startTunnelWhenReady();
    }

    // Check if we should show the "Connect AI" banner
    if (!_aiSetupDismissed && _cameras.isNotEmpty) {
      final apps = AIAppService.detectApps();
      final hasConfigured = AIAppService.hasAnyConfigured(apps);
      if (!hasConfigured && mounted) {
        setState(() => _showAIBanner = true);
      }
    }
  }

  Future<void> _refreshData() async {
    await _loadData();
  }

  /// Wait for the MCP server to be ready, then start the Cloudflare Tunnel.
  ///
  /// This prevents the race condition where the tunnel connects before the
  /// MCP server (uvicorn on port 8400) is ready, causing Cloudflare to
  /// return an error HTML page instead of proxying to the backend.
  Future<void> _startTunnelWhenReady() async {
    final mcpPort = _backendManager.mcpPort;
    debugPrint('[AppShell] Waiting for MCP server on port $mcpPort before starting tunnel...');

    // Check if MCP is already ready (usually is by this point)
    bool mcpReady = await _backendManager.isMcpReady();

    if (!mcpReady) {
      // Poll for up to 30 seconds
      for (int i = 0; i < 60; i++) {
        await Future.delayed(const Duration(milliseconds: 500));
        if (!mounted) return;
        mcpReady = await _backendManager.isMcpReady();
        if (mcpReady) break;
      }
    }

    if (!mounted) return;

    if (mcpReady) {
      debugPrint('[AppShell] MCP server confirmed ready — starting tunnel...');
    } else {
      debugPrint('[AppShell] MCP server not ready after 30s — starting tunnel anyway');
    }

    // Stop existing tunnel first (handles restart case)
    if (_tunnelManager.state == TunnelState.running ||
        _tunnelManager.state == TunnelState.starting) {
      await _tunnelManager.stop();
    }

    final ok = await _tunnelManager.start(port: mcpPort);
    if (mounted && ok) {
      debugPrint('[AppShell] Tunnel ready: ${_tunnelManager.publicUrl}');
      setState(() {}); // Refresh UI with tunnel URL
    } else if (mounted) {
      debugPrint('[AppShell] Tunnel failed to start');
      setState(() {}); // Refresh UI to show error state
    }
  }

  void _navigateToConnectAI() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ConnectAIScreen(
          serverPort: _serverConfig?.port ?? 8090,
          tunnelUrl: _tunnelManager.publicUrl,
          onDone: () {
            Navigator.of(context).pop();
            setState(() {
              _showAIBanner = false;
              _aiSetupDismissed = true;
            });
          },
        ),
      ),
    );
  }

  // ── Rule Actions ────────────────────────────────────────────

  Future<void> _createRule({
    required String name,
    required String condition,
    String? cameraId,
    required String priority,
    required String notificationType,
    required int cooldownSeconds,
  }) async {
    if (_apiClient == null) return;
    try {
      final rule = await _apiClient!.createRule(
        name: name,
        condition: condition,
        cameraId: cameraId,
        priority: priority,
        notificationType: notificationType,
        cooldownSeconds: cooldownSeconds,
      );
      setState(() => _rules.add(rule));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to create rule: $e'),
            backgroundColor: DJIColors.danger,
          ),
        );
      }
    }
  }

  Future<void> _toggleRule(WatchRule rule) async {
    if (_apiClient == null) return;
    try {
      final updated = await _apiClient!.toggleRule(rule.id);
      setState(() {
        final idx = _rules.indexWhere((r) => r.id == rule.id);
        if (idx >= 0) _rules[idx] = updated;
      });
    } catch (e) {
      // Toggle locally as fallback
      setState(() {
        final idx = _rules.indexWhere((r) => r.id == rule.id);
        if (idx >= 0) {
          _rules[idx] = rule.copyWith(enabled: !rule.enabled);
        }
      });
    }
  }

  Future<void> _deleteRule(WatchRule rule) async {
    if (_apiClient == null) return;
    try {
      await _apiClient!.deleteRule(rule.id);
      setState(() => _rules.removeWhere((r) => r.id == rule.id));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to delete rule: $e'),
            backgroundColor: DJIColors.danger,
          ),
        );
      }
    }
  }

  // ── Build ───────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    switch (_state) {
      case _AppState.onboarding:
        return OnboardingScreen(
          isEmbedded: _backendManager.isEmbedded,
          onComplete: () async {
            final prefs = await SharedPreferences.getInstance();
            await prefs.setBool('onboarding_completed', true);

            // If embedded, start backend before proceeding
            if (_backendManager.isEmbedded) {
              setState(() => _state = _AppState.starting);
              await _backendManager.start();
            }

            await _loadSavedConfig();
            setState(() => _state = _AppState.splash);
          },
        );

      case _AppState.starting:
        return _buildStartingScreen();

      case _AppState.splash:
        return SplashScreen(
          onCheckConnection: _checkSavedConnection,
          onConnected: () async {
            debugPrint('[AppShell] onConnected fired, loading data...');
            await _loadData();
            _startHealthCheck();
            _connectSse();
            _fetchProviderInfo();
            debugPrint('[AppShell] Data loaded, switching to main state');
            setState(() => _state = _AppState.main);
          },
          onNotFound: () => setState(() => _state = _AppState.connect),
        );

      case _AppState.connect:
        return ConnectScreen(
          discoveredServers: _discoveredServers,
          isScanning: _isScanning,
          isEmbedded: _backendManager.isEmbedded,
          onConnect: _connectTo,
          onRescan: _rescan,
          onRestartServer: _backendManager.isEmbedded
              ? () async {
                  setState(() => _state = _AppState.starting);
                  await _backendManager.restart();
                  await _loadSavedConfig();
                  setState(() => _state = _AppState.splash);
                }
              : null,
        );

      case _AppState.main:
        return _buildMainApp();
    }
  }

  Widget _buildStartingScreen() {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const AppLogo(size: 88)
                .animate(onPlay: (c) => c.repeat(reverse: true))
                .scale(
                  begin: const Offset(0.95, 0.95),
                  end: const Offset(1.05, 1.05),
                  duration: 1200.ms,
                ),
            const SizedBox(height: DJISpacing.xxxl),
            const Text(
              'Starting camera server...',
              style: TextStyle(
                color: DJIColors.textPrimary,
                fontSize: 18,
                fontWeight: FontWeight.w500,
              ),
            ).animate().fadeIn(duration: 400.ms),
            const SizedBox(height: DJISpacing.xl),
            SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                color: DJIColors.primary,
                strokeWidth: 2,
              ),
            ),
            const SizedBox(height: DJISpacing.xxl),
            Text(
              'First launch may take a few seconds',
              style: TextStyle(
                color: DJIColors.textTertiary,
                fontSize: 13,
              ),
            ).animate().fadeIn(delay: 3.seconds, duration: 500.ms),
          ],
        ),
      ),
    );
  }

  Widget _buildMainApp() {
    final screens = [
      // Home — Dashboard
      DashboardScreen(
        cameras: _cameras,
        isLoading: _isLoading,
        serverBaseUrl: _serverConfig?.baseUrl ?? 'http://localhost:8090',
        headers: _serverConfig?.headers,
        onCameraTap: (camera) {
          Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => LiveViewScreen(
                camera: camera,
                apiClient: _apiClient!,
              ),
            ),
          );
        },
        onAddCamera: () {
          setState(() => _state = _AppState.connect);
        },
        onRefresh: _refreshData,
      ),

      // Alerts
      AlertsScreen(
        alerts: _filterPriority != null
            ? _alerts.where((a) => a.priority == _filterPriority).toList()
            : _alerts,
        isLoading: _isLoading,
        onRefresh: _refreshData,
        filterPriority: _filterPriority,
        onFilterChanged: (p) => setState(() => _filterPriority = p),
      ),

      // Rules
      RulesScreen(
        rules: _rules,
        cameras: _cameras,
        isLoading: _isLoading,
        onToggle: _toggleRule,
        onDelete: _deleteRule,
        onCreateRule: ({
          required name,
          required condition,
          cameraId,
          required priority,
          required notificationType,
          required cooldownSeconds,
        }) {
          _createRule(
            name: name,
            condition: condition,
            cameraId: cameraId,
            priority: priority,
            notificationType: notificationType,
            cooldownSeconds: cooldownSeconds,
          );
        },
      ),

      // Settings
      SettingsScreen(
        serverName: _serverConfig?.name ?? 'Unknown',
        serverHost: _serverConfig?.host ?? '',
        serverPort: _serverConfig?.port ?? 8090,
        isConnected: _isConnected && !_connectionLost,
        aiProvider: _aiProvider,
        aiModel: _aiModel,
        tunnelUrl: _tunnelManager.publicUrl,
        tunnelState: _tunnelManager.state,
        onDisconnect: () {
          _healthTimer?.cancel();
          _sseClient?.dispose();
          _sseClient = null;
          _apiClient?.dispose();
          _apiClient = null;
          _serverConfig = null;
          _isConnected = false;
          _connectionLost = false;
          setState(() => _state = _AppState.connect);
        },
        onTestConnection: () async {
          final healthy = await _apiClient?.isHealthy() ?? false;
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(healthy ? 'Connection OK' : 'Connection failed'),
                backgroundColor:
                    healthy ? DJIColors.secondary : DJIColors.danger,
              ),
            );
          }
        },
        onConfigureProvider: _showProviderConfigDialog,
        onManageAIApps: _navigateToConnectAI,
      ),
    ];

    return Scaffold(
      body: Column(
        children: [
          // Connect AI banner
          if (_showAIBanner && !_connectionLost && _currentTab == 0)
            MaterialBanner(
              backgroundColor: DJIColors.primary.withValues(alpha: 0.12),
              padding: const EdgeInsets.symmetric(
                horizontal: DJISpacing.lg,
                vertical: DJISpacing.sm,
              ),
              leading: Icon(
                _tunnelManager.state == TunnelState.running
                    ? Icons.cloud_done_rounded
                    : Icons.smart_toy_rounded,
                color: DJIColors.primary,
                size: 20,
              ),
              content: Text(
                _tunnelManager.state == TunnelState.running
                    ? 'Tunnel active — connect ChatGPT or another AI app'
                    : 'Connect an AI app to get started',
                style: const TextStyle(
                  color: DJIColors.primary,
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => setState(() {
                    _showAIBanner = false;
                    _aiSetupDismissed = true;
                  }),
                  child: const Text(
                    'Dismiss',
                    style: TextStyle(color: DJIColors.textTertiary, fontSize: 12),
                  ),
                ),
                TextButton(
                  onPressed: _navigateToConnectAI,
                  child: const Text(
                    'Set Up',
                    style: TextStyle(color: DJIColors.primary),
                  ),
                ),
              ],
            ),
          // Connection loss banner
          if (_connectionLost)
            MaterialBanner(
              backgroundColor: DJIColors.danger.withValues(alpha: 0.15),
              padding: const EdgeInsets.symmetric(
                horizontal: DJISpacing.lg,
                vertical: DJISpacing.sm,
              ),
              leading: const Icon(
                Icons.cloud_off_rounded,
                color: DJIColors.danger,
                size: 20,
              ),
              content: const Text(
                'Connection lost — Reconnecting...',
                style: TextStyle(
                  color: DJIColors.danger,
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () async {
                    final healthy =
                        await _apiClient?.isHealthy() ?? false;
                    if (healthy && mounted) {
                      setState(() {
                        _connectionLost = false;
                        _isConnected = true;
                      });
                      _loadData();
                    }
                  },
                  child: const Text(
                    'Retry',
                    style: TextStyle(color: DJIColors.danger),
                  ),
                ),
              ],
            ),
          Expanded(
            child: IndexedStack(
              index: _currentTab,
              children: screens,
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentTab,
        onDestinationSelected: (idx) => setState(() => _currentTab = idx),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.home_rounded),
            selectedIcon: const Icon(Icons.home_rounded),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: _alerts.isNotEmpty,
              label: Text('${_alerts.length}'),
              child: const Icon(Icons.notifications_rounded),
            ),
            label: 'Alerts',
          ),
          NavigationDestination(
            icon: const Icon(Icons.visibility_rounded),
            selectedIcon: const Icon(Icons.visibility_rounded),
            label: 'Rules',
          ),
          NavigationDestination(
            icon: const Icon(Icons.settings_rounded),
            selectedIcon: const Icon(Icons.settings_rounded),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}

enum _AppState { onboarding, starting, splash, connect, main }
