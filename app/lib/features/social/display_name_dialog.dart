import 'package:flutter/material.dart';

import 'package:mindmeld/social/social_service.dart';

/// Default max length for a display name — matches [kDisplayNameMaxLength].
/// Callers naming a GROUP should pass [kGroupNameMaxLength] instead.
const int kDisplayNamePromptMaxLength = kDisplayNameMaxLength;

/// Prompt the player for a leaderboard display name or a group name.
///
/// Returns the trimmed name, or null if the player cancelled. [maxLength]
/// must match whichever Firestore rules bound applies to the field being
/// named — 40 for a display name ([kDisplayNameMaxLength], the default), 60
/// for a group name ([kGroupNameMaxLength]). This dialog does NOT itself
/// sanitize/moderate the input — see [promptValidatedName], which wraps this
/// with the real validation + friendly re-prompt loop.
Future<String?> promptDisplayName(
  BuildContext context, {
  String? initial,
  String title = 'Choose a display name',
  int maxLength = kDisplayNamePromptMaxLength,
  String? errorText,
}) {
  final controller = TextEditingController(text: initial ?? '');
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: controller,
        autofocus: true,
        maxLength: maxLength,
        decoration: InputDecoration(
          hintText: 'e.g. Gaurav',
          labelText: 'Display name',
          errorText: errorText,
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

/// Generic friendly rejection shown for ANY sanitization/moderation failure
/// — deliberately never says WHICH rule was violated (length, profanity,
/// reserved word, etc.), per the launch-hardening spec's moderation
/// requirement.
const String kNameRejectedMessage = "That name isn't allowed — try something else";

/// Prompt for a name, looping with an inline friendly rejection until the
/// player enters one that passes [validateName] (sanitization + moderation)
/// or cancels.
///
/// This is the preferred entry point for any UI that collects a display
/// name or group name — it re-shows [promptDisplayName] with
/// [kNameRejectedMessage] as inline `errorText` (pre-filled with the
/// player's previous attempt) rather than dismissing on a bad name, and
/// reuses the EXACT SAME validation `SocialService.setDisplayName`/
/// `createGroup` enforce server-write-side — this is a UX convenience for
/// immediate feedback, not a substitute for that enforcement.
Future<String?> promptValidatedName(
  BuildContext context, {
  String? initial,
  String title = 'Choose a display name',
  int maxLength = kDisplayNamePromptMaxLength,
}) async {
  String? current = initial;
  String? errorText;
  while (true) {
    if (!context.mounted) return null;
    final input = await promptDisplayName(
      context,
      initial: current,
      title: title,
      maxLength: maxLength,
      errorText: errorText,
    );
    if (input == null) return null;
    final result = validateName(input, maxLength: maxLength);
    if (result.isOk) return result.cleaned;
    current = input;
    errorText = kNameRejectedMessage;
  }
}
