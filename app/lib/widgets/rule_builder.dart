import 'package:flutter/material.dart';

import '../models/camera.dart';
import '../theme/dji_theme.dart';

/// Visual rule creation bottom sheet.
///
/// Natural language condition input with camera picker and priority selector.
class RuleBuilder extends StatefulWidget {
  final List<Camera> cameras;
  final void Function({
    required String name,
    required String condition,
    String? cameraId,
    required String priority,
    required String notificationType,
    required int cooldownSeconds,
  }) onSubmit;

  const RuleBuilder({
    super.key,
    required this.cameras,
    required this.onSubmit,
  });

  @override
  State<RuleBuilder> createState() => _RuleBuilderState();
}

class _RuleBuilderState extends State<RuleBuilder> {
  final _nameController = TextEditingController();
  final _conditionController = TextEditingController();
  String? _selectedCameraId;
  String _priority = 'medium';
  String _notificationType = 'local';
  final int _cooldownSeconds = 60;

  final _priorities = ['low', 'medium', 'high', 'critical'];
  final _notificationTypes = ['local', 'desktop', 'ntfy'];

  bool get _isValid =>
      _nameController.text.isNotEmpty &&
      _conditionController.text.isNotEmpty;

  @override
  void dispose() {
    _nameController.dispose();
    _conditionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: DJIColors.surfaceElevated,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      padding: EdgeInsets.only(
        left: DJISpacing.xl,
        right: DJISpacing.xl,
        top: DJISpacing.lg,
        bottom: MediaQuery.of(context).viewInsets.bottom + DJISpacing.xl,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Handle
            Center(
              child: Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: DJIColors.textTertiary,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: DJISpacing.xl),

            // Title
            const Text(
              'Create Watch Rule',
              style: TextStyle(
                color: DJIColors.textPrimary,
                fontSize: 22,
                fontWeight: FontWeight.w600,
                letterSpacing: -0.4,
              ),
            ),
            const SizedBox(height: DJISpacing.xs),
            const Text(
              'Tell the AI what to watch for',
              style: TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 14,
              ),
            ),
            const SizedBox(height: DJISpacing.xxl),

            // Name field
            TextField(
              controller: _nameController,
              style: const TextStyle(color: DJIColors.textPrimary),
              decoration: const InputDecoration(
                labelText: 'Rule name',
                hintText: 'e.g. "Watch the front door"',
              ),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: DJISpacing.lg),

            // Condition field
            TextField(
              controller: _conditionController,
              style: const TextStyle(color: DJIColors.textPrimary),
              decoration: const InputDecoration(
                labelText: 'Condition (natural language)',
                hintText: 'e.g. "Someone approaches the door"',
              ),
              maxLines: 2,
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: DJISpacing.lg),

            // Camera picker
            if (widget.cameras.isNotEmpty) ...[
              const Text(
                'Camera',
                style: TextStyle(
                  color: DJIColors.textSecondary,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: DJISpacing.sm),
              Wrap(
                spacing: DJISpacing.sm,
                children: [
                  _ChoiceChipButton(
                    label: 'All cameras',
                    selected: _selectedCameraId == null,
                    onTap: () => setState(() => _selectedCameraId = null),
                  ),
                  ...widget.cameras.map((cam) => _ChoiceChipButton(
                        label: cam.name,
                        selected: _selectedCameraId == cam.id,
                        onTap: () =>
                            setState(() => _selectedCameraId = cam.id),
                      )),
                ],
              ),
              const SizedBox(height: DJISpacing.lg),
            ],

            // Priority picker
            const Text(
              'Priority',
              style: TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: DJISpacing.sm),
            Wrap(
              spacing: DJISpacing.sm,
              children: _priorities.map((p) {
                final color = DJIColors.forPriority(p);
                return _ChoiceChipButton(
                  label: p[0].toUpperCase() + p.substring(1),
                  selected: _priority == p,
                  color: color,
                  onTap: () => setState(() => _priority = p),
                );
              }).toList(),
            ),
            const SizedBox(height: DJISpacing.lg),

            // Notification type
            const Text(
              'Notification',
              style: TextStyle(
                color: DJIColors.textSecondary,
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: DJISpacing.sm),
            Wrap(
              spacing: DJISpacing.sm,
              children: _notificationTypes.map((t) {
                return _ChoiceChipButton(
                  label: t == 'ntfy' ? 'Push' : t[0].toUpperCase() + t.substring(1),
                  selected: _notificationType == t,
                  onTap: () => setState(() => _notificationType = t),
                );
              }).toList(),
            ),
            const SizedBox(height: DJISpacing.xxl),

            // Submit button
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _isValid
                    ? () {
                        widget.onSubmit(
                          name: _nameController.text,
                          condition: _conditionController.text,
                          cameraId: _selectedCameraId,
                          priority: _priority,
                          notificationType: _notificationType,
                          cooldownSeconds: _cooldownSeconds,
                        );
                        Navigator.of(context).pop();
                      }
                    : null,
                child: const Text('Create Rule'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ChoiceChipButton extends StatelessWidget {
  final String label;
  final bool selected;
  final Color? color;
  final VoidCallback onTap;

  const _ChoiceChipButton({
    required this.label,
    required this.selected,
    this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final chipColor = color ?? DJIColors.primary;

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: selected
              ? chipColor.withValues(alpha: 0.15)
              : DJIColors.surface,
          borderRadius: BorderRadius.circular(DJIRadius.round),
          border: Border.all(
            color: selected
                ? chipColor.withValues(alpha: 0.5)
                : DJIColors.border,
            width: 1,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? chipColor : DJIColors.textSecondary,
            fontSize: 13,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ),
    );
  }
}
