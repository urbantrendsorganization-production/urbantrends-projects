import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_exception.dart';
import '../api/applications_repository.dart';
import '../api/models.dart';
import '../shared/ui.dart';
import 'onboarding_controller.dart';
import 'steps/client_details_step.dart';
import 'steps/consent_step.dart';
import 'steps/documents_step.dart';
import 'steps/review_step.dart';
import 'steps/verification_step.dart';

/// Hosts the 5-step onboarding stepper for one application (CLAUDE.md §12).
/// Returned applications surface reviewer notes at the top and re-open editing.
/// Submitted / terminal applications render read-only.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key, required this.applicationId});

  final String applicationId;

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  int _step = 0;

  @override
  Widget build(BuildContext context) {
    final detailAsync =
        ref.watch(onboardingControllerProvider(widget.applicationId));

    return Scaffold(
      appBar: AppBar(title: const Text('Onboarding')),
      body: detailAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => ErrorRetry(
          message: err is ApiException ? err.message : 'Could not load the application.',
          onRetry: () => ref
              .read(onboardingControllerProvider(widget.applicationId).notifier)
              .reload(),
        ),
        data: (detail) => detail.application.status.isEditable
            ? _buildStepper(context, detail)
            : _ReadOnlyView(detail: detail),
      ),
    );
  }

  Widget _buildStepper(BuildContext context, ApplicationDetail detail) {
    final id = widget.applicationId;
    final notes = detail.application.status == AppStatus.returnedForCorrection
        ? detail.reviewerNotes
        : null;

    final steps = <_OnboardStep>[
      _OnboardStep(
        title: 'Client details',
        complete: _clientDetailsComplete(detail.client),
        content: ClientDetailsStep(applicationId: id, detail: detail),
      ),
      _OnboardStep(
        title: 'Documents',
        complete: _documentsComplete(detail),
        content: DocumentsStep(applicationId: id, detail: detail),
      ),
      _OnboardStep(
        title: 'Phone verification',
        complete: detail.application.otpVerified,
        content: VerificationStep(applicationId: id, detail: detail),
      ),
      _OnboardStep(
        title: 'Consent',
        complete: detail.application.consentGiven,
        content: ConsentStep(applicationId: id, detail: detail),
      ),
      _OnboardStep(
        title: 'Review & submit',
        complete: false,
        content: ReviewStep(
          applicationId: id,
          detail: detail,
          onSubmitted: () => Navigator.of(context).maybePop(),
        ),
      ),
    ];

    final clamped = _step.clamp(0, steps.length - 1);

    return Column(
      children: [
        if (notes != null) ReviewerNotesBanner(notes: notes),
        Expanded(
          child: Stepper(
            currentStep: clamped,
            onStepTapped: (i) => setState(() => _step = i),
            onStepContinue: clamped < steps.length - 1
                ? () => setState(() => _step = clamped + 1)
                : null,
            onStepCancel:
                clamped > 0 ? () => setState(() => _step = clamped - 1) : null,
            controlsBuilder: (context, details) {
              final isLast = details.stepIndex == steps.length - 1;
              return Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Row(
                  children: [
                    if (!isLast)
                      FilledButton(
                        onPressed: details.onStepContinue,
                        child: const Text('Next'),
                      ),
                    if (details.stepIndex > 0) ...[
                      const SizedBox(width: 8),
                      TextButton(
                        onPressed: details.onStepCancel,
                        child: const Text('Back'),
                      ),
                    ],
                  ],
                ),
              );
            },
            steps: [
              for (var i = 0; i < steps.length; i++)
                Step(
                  title: Text(steps[i].title),
                  isActive: i <= clamped,
                  state: steps[i].complete
                      ? StepState.complete
                      : (i == clamped ? StepState.editing : StepState.indexed),
                  content: steps[i].content,
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _OnboardStep {
  const _OnboardStep({
    required this.title,
    required this.complete,
    required this.content,
  });
  final String title;
  final bool complete;
  final Widget content;
}

/// Client details are considered complete when every field the submit
/// validation implicitly relies on is filled (a superset is fine — the backend
/// is the final authority).
bool _clientDetailsComplete(ClientModel c) =>
    c.fullName.trim().isNotEmpty &&
    (c.phone?.isNotEmpty ?? false) &&
    (c.nationalIdNumber?.isNotEmpty ?? false) &&
    c.dateOfBirth != null &&
    (c.address?.isNotEmpty ?? false);

bool _documentsComplete(ApplicationDetail detail) => kRequiredDocTypes.every(
      (t) => detail.documentFor(t)?.processed ?? false,
    );

/// Read-only view for submitted / terminal applications: status, client number
/// (once approved), and the event history.
class _ReadOnlyView extends StatelessWidget {
  const _ReadOnlyView({required this.detail});

  final ApplicationDetail detail;

  @override
  Widget build(BuildContext context) {
    final app = detail.application;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                detail.client.fullName,
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            StatusBadge(status: app.status),
          ],
        ),
        const SizedBox(height: 8),
        Text('Product: ${app.productCode}'),
        if (detail.client.clientNumber != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('Client number: ${detail.client.clientNumber}'),
          ),
        if (app.status == AppStatus.rejected && detail.events.isNotEmpty) ...[
          const SizedBox(height: 12),
          _rejectionReason(detail),
        ],
        const Divider(height: 32),
        Text('History', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        for (final e in detail.events.reversed)
          ListTile(
            dense: true,
            leading: const Icon(Icons.history),
            title: Text(e.toStatus.label),
            subtitle: e.reason == null ? null : Text(e.reason!),
          ),
      ],
    );
  }

  Widget _rejectionReason(ApplicationDetail detail) {
    final reason = detail.events.reversed
        .firstWhere(
          (e) => e.toStatus == AppStatus.rejected,
          orElse: () => detail.events.last,
        )
        .reason;
    if (reason == null || reason.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.shade50,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text('Reason: $reason'),
    );
  }
}
