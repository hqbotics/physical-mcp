import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../models/camera.dart';
import '../models/rule.dart';
import '../theme/dji_theme.dart';
import '../widgets/glassmorphic_card.dart';
import '../widgets/rule_builder.dart';

/// Rules manager screen — list of active watch rules with add/toggle/delete.
class RulesScreen extends StatelessWidget {
  final List<WatchRule> rules;
  final List<Camera> cameras;
  final bool isLoading;
  final void Function(WatchRule rule) onToggle;
  final void Function(WatchRule rule) onDelete;
  final void Function({
    required String name,
    required String condition,
    String? cameraId,
    required String priority,
    required String notificationType,
    required int cooldownSeconds,
  }) onCreateRule;

  const RulesScreen({
    super.key,
    required this.rules,
    required this.cameras,
    this.isLoading = false,
    required this.onToggle,
    required this.onDelete,
    required this.onCreateRule,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DJIColors.background,
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.all(DJISpacing.xl),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Watch Rules',
                    style: TextStyle(
                      color: DJIColors.textPrimary,
                      fontSize: 28,
                      fontWeight: FontWeight.w600,
                      letterSpacing: -0.5,
                    ),
                  ),
                  const SizedBox(height: DJISpacing.sm),
                  Text(
                    '${rules.where((r) => r.enabled).length} active of ${rules.length} rules',
                    style: const TextStyle(
                      color: DJIColors.textSecondary,
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
            ),

            // Rules list
            Expanded(
              child: rules.isEmpty
                  ? _buildEmptyState(context)
                  : ListView.builder(
                      padding: const EdgeInsets.symmetric(
                        horizontal: DJISpacing.xl,
                      ),
                      itemCount: rules.length,
                      itemBuilder: (context, index) {
                        final rule = rules[index];
                        return _RuleCard(
                          rule: rule,
                          onToggle: () => onToggle(rule),
                          onDelete: () => onDelete(rule),
                        )
                            .animate()
                            .fadeIn(
                              delay: Duration(milliseconds: 50 * index),
                              duration: 300.ms,
                            );
                      },
                    ),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showRuleBuilder(context),
        icon: const Icon(Icons.add_rounded, size: 20),
        label: const Text('Add Rule'),
      ),
    );
  }

  Widget _buildEmptyState(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.visibility_rounded,
            size: 64,
            color: DJIColors.textTertiary,
          ),
          const SizedBox(height: DJISpacing.lg),
          const Text(
            'No watch rules',
            style: TextStyle(
              color: DJIColors.textSecondary,
              fontSize: 18,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: DJISpacing.sm),
          const Text(
            'Create rules to tell the AI\nwhat to watch for',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: DJIColors.textTertiary,
              fontSize: 14,
            ),
          ),
          const SizedBox(height: DJISpacing.xxl),
          ElevatedButton.icon(
            onPressed: () => _showRuleBuilder(context),
            icon: const Icon(Icons.add_rounded, size: 18),
            label: const Text('Create First Rule'),
          ),
        ],
      ),
    );
  }

  void _showRuleBuilder(BuildContext context) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => RuleBuilder(
        cameras: cameras,
        onSubmit: onCreateRule,
      ),
    );
  }
}

class _RuleCard extends StatelessWidget {
  final WatchRule rule;
  final VoidCallback onToggle;
  final VoidCallback onDelete;

  const _RuleCard({
    required this.rule,
    required this.onToggle,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final priorityColor = DJIColors.forPriority(rule.priority);

    return Dismissible(
      key: Key(rule.id),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: DJISpacing.xl),
        margin: const EdgeInsets.only(bottom: DJISpacing.md),
        decoration: BoxDecoration(
          color: DJIColors.danger.withValues(alpha: 0.15),
          borderRadius: DJIRadius.cardRadius,
        ),
        child: const Icon(
          Icons.delete_rounded,
          color: DJIColors.danger,
        ),
      ),
      onDismissed: (_) => onDelete(),
      child: GlassmorphicCard(
        margin: const EdgeInsets.only(bottom: DJISpacing.md),
        padding: const EdgeInsets.all(DJISpacing.lg),
        child: Row(
          children: [
            // Priority indicator
            Container(
              width: 4,
              height: 50,
              decoration: BoxDecoration(
                color: rule.enabled
                    ? priorityColor
                    : DJIColors.textTertiary,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: DJISpacing.md),

            // Rule info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    rule.name,
                    style: TextStyle(
                      color: rule.enabled
                          ? DJIColors.textPrimary
                          : DJIColors.textTertiary,
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    rule.condition,
                    style: TextStyle(
                      color: rule.enabled
                          ? DJIColors.textSecondary
                          : DJIColors.textTertiary,
                      fontSize: 13,
                    ),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: DJISpacing.xs),
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 1,
                        ),
                        decoration: BoxDecoration(
                          color: priorityColor.withValues(alpha: 0.15),
                          borderRadius:
                              BorderRadius.circular(DJIRadius.round),
                        ),
                        child: Text(
                          rule.priority,
                          style: TextStyle(
                            color: priorityColor,
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      if (rule.triggerCount > 0) ...[
                        const SizedBox(width: DJISpacing.sm),
                        Text(
                          '${rule.triggerCount} triggers',
                          style: const TextStyle(
                            color: DJIColors.textTertiary,
                            fontSize: 10,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),

            // Enable/disable toggle
            Switch(
              value: rule.enabled,
              onChanged: (_) => onToggle(),
            ),
          ],
        ),
      ),
    );
  }
}
