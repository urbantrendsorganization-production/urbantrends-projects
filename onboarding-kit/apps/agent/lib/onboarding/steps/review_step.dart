import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/applications_repository.dart';
import '../../api/models.dart';
import '../../shared/ui.dart';
import '../onboarding_controller.dart';

/// Step 5 — a completeness checklist mirroring the backend submit validation
/// (§6/§12: 4 docs processed, OTP verified, consent recorded), then submit.
class ReviewStep extends ConsumerStatefulWidget {
  const ReviewStep({
    super.key,
    required this.applicationId,
    required this.detail,
    required this.onSubmitted,
  });

  final String applicationId;
  final ApplicationDetail detail;

  /// Called after a successful submit (used to pop back to the queue).
  final VoidCallback onSubmitted;

  @override
  ConsumerState<ReviewStep> createState() => _ReviewStepState();
}

class _ReviewStepState extends ConsumerState<ReviewStep> {
  bool _submitting = false;

  OnboardingController get _controller =>
      ref.read(onboardingControllerProvider(widget.applicationId).notifier);

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await _controller.submit();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Application submitted for review.')),
      );
      widget.onSubmitted();
    } catch (e) {
      if (mounted) {
        showErrorSnack(
          context,
          e is ApiException ? e.message : 'Could not submit. Try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final detail = widget.detail;
    final client = detail.client;

    final docsDone = kRequiredDocTypes
        .where((t) => detail.documentFor(t)?.processed ?? false)
        .length;
    final docsComplete = docsDone == kRequiredDocTypes.length;
    final detailsComplete = client.fullName.trim().isNotEmpty &&
        (client.phone?.isNotEmpty ?? false) &&
        (client.nationalIdNumber?.isNotEmpty ?? false) &&
        client.dateOfBirth != null &&
        (client.address?.isNotEmpty ?? false);

    final checks = <_Check>[
      _Check('Client details captured', detailsComplete),
      _Check('Documents uploaded & processed ($docsDone/4)', docsComplete),
      _Check('Client phone verified', detail.application.otpVerified),
      _Check('Consent recorded', detail.application.consentGiven),
    ];
    final allDone = checks.every((c) => c.done);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final c in checks)
          ListTile(
            contentPadding: EdgeInsets.zero,
            dense: true,
            leading: Icon(
              c.done ? Icons.check_circle : Icons.radio_button_unchecked,
              color: c.done
                  ? Colors.green
                  : Theme.of(context).colorScheme.outline,
            ),
            title: Text(c.label),
          ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: (allDone && !_submitting) ? _submit : null,
          icon: _submitting
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.send),
          label: const Text('Submit for review'),
        ),
        if (!allDone)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              'Complete every step above to submit.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
      ],
    );
  }
}

class _Check {
  const _Check(this.label, this.done);
  final String label;
  final bool done;
}
