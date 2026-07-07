import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models.dart';
import '../../config.dart';
import '../../shared/ui.dart';
import '../onboarding_controller.dart';

/// Step 4 — render the terms and record the client's consent for the current
/// terms version (CLAUDE.md §12). The backend rejects a stale version.
class ConsentStep extends ConsumerStatefulWidget {
  const ConsentStep({
    super.key,
    required this.applicationId,
    required this.detail,
  });

  final String applicationId;
  final ApplicationDetail detail;

  @override
  ConsumerState<ConsentStep> createState() => _ConsentStepState();
}

class _ConsentStepState extends ConsumerState<ConsentStep> {
  bool _accepted = false;
  bool _saving = false;

  static const _terms = '''
By proceeding, the client agrees that:

• The personal information and documents provided are true and belong to the client.
• The information may be used to open and service their account, and for identity verification and regulatory compliance.
• The client consents to being contacted on the phone number provided.
• The client may request correction or deletion of their data in line with the Kenya Data Protection Act (2019).

The field agent confirms the client reviewed and accepted these terms.''';

  OnboardingController get _controller =>
      ref.read(onboardingControllerProvider(widget.applicationId).notifier);

  Future<void> _record() async {
    setState(() => _saving = true);
    try {
      await _controller.recordConsent(AppConfig.consentTermsVersion);
    } catch (e) {
      if (mounted) {
        showErrorSnack(
          context,
          e is ApiException ? e.message : 'Could not record consent.',
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = widget.detail.application;
    if (app.consentGiven) {
      return Row(
        children: [
          const Icon(Icons.verified_user, color: Colors.green),
          const SizedBox(width: 8),
          Text(
            'Consent recorded'
            '${app.consentTermsVersion != null ? ' (${app.consentTermsVersion})' : ''}',
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(_terms, style: Theme.of(context).textTheme.bodySmall),
        ),
        const SizedBox(height: 8),
        Text(
          'Terms version: ${AppConfig.consentTermsVersion}',
          style: Theme.of(context).textTheme.labelSmall,
        ),
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          value: _accepted,
          onChanged: (v) => setState(() => _accepted = v ?? false),
          title: const Text('The client has read and accepts these terms.'),
        ),
        FilledButton(
          onPressed: (_accepted && !_saving) ? _record : null,
          child: _saving
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Record consent'),
        ),
      ],
    );
  }
}
