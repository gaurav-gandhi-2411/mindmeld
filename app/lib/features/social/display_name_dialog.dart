import 'package:flutter/material.dart';

/// Prompt the player for a leaderboard display name.
///
/// Returns the trimmed name, or null if the player cancelled. Enforces the
/// same 1-40 char bound the Firestore rules require.
Future<String?> promptDisplayName(
  BuildContext context, {
  String? initial,
  String title = 'Choose a display name',
}) {
  final controller = TextEditingController(text: initial ?? '');
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: controller,
        autofocus: true,
        maxLength: 40,
        decoration: const InputDecoration(
          hintText: 'e.g. Gaurav',
          labelText: 'Display name',
        ),
        onSubmitted: (v) {
          final trimmed = v.trim();
          if (trimmed.isNotEmpty) Navigator.pop(ctx, trimmed);
        },
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            final trimmed = controller.text.trim();
            if (trimmed.isNotEmpty) Navigator.pop(ctx, trimmed);
          },
          child: const Text('Continue'),
        ),
      ],
    ),
  );
}
