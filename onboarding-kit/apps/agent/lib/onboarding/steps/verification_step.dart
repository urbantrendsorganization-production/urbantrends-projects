import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_exception.dart';
import '../../api/models.dart';
import '../../shared/ui.dart';
import '../onboarding_controller.dart';

/// Step 3 — verify the CLIENT's phone via OTP (CLAUDE.md §8/§12). The code is
/// sent to the client's number captured in step 1.
class VerificationStep extends ConsumerStatefulWidget {
  const VerificationStep({
    super.key,
    required this.applicationId,
    required this.detail,
  });

  final String applicationId;
  final ApplicationDetail detail;

  @override
  ConsumerState<VerificationStep> createState() => _VerificationStepState();
}

class _VerificationStepState extends ConsumerState<VerificationStep> {
  final _code = TextEditingController();
  bool _sending = false;
  bool _verifying = false;
  bool _sent = false;
  DateTime? _expiresAt;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  OnboardingController get _controller =>
      ref.read(onboardingControllerProvider(widget.applicationId).notifier);

  /// Mask to the last 3 digits for display (§3: never expose full phones).
  String _maskPhone(String phone) {
    if (phone.length <= 3) return phone;
    final tail = phone.substring(phone.length - 3);
    return '${'•' * (phone.length - 3)}$tail';
  }

  Future<void> _send() async {
    setState(() => _sending = true);
    try {
      final result = await _controller.sendOtp();
      if (!mounted) return;
      setState(() {
        _sent = true;
        _expiresAt = result.expiresAt;
      });
      // Dev-only convenience (§8): the code is surfaced only when the backend
      // runs with DEV_EXPOSE_OTP=true. Never present in production.
      final devCode = result.devCode;
      final message = devCode != null
          ? 'Code sent. Dev code: $devCode'
          : 'Code sent to the client’s phone.';
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    } catch (e) {
      if (mounted) {
        showErrorSnack(
          context,
          e is ApiException ? e.message : 'Could not send the code.',
        );
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _verify() async {
    final code = _code.text.trim();
    if (code.isEmpty) {
      showErrorSnack(context, 'Enter the code the client received.');
      return;
    }
    setState(() => _verifying = true);
    try {
      await _controller.verifyOtp(code);
      // Success flows through the controller reload -> otpVerified flips true.
    } catch (e) {
      if (mounted) {
        showErrorSnack(
          context,
          e is ApiException ? e.message : 'Verification failed.',
        );
      }
    } finally {
      if (mounted) setState(() => _verifying = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final client = widget.detail.client;
    final verified = widget.detail.application.otpVerified;

    if (verified) {
      return const Row(
        children: [
          Icon(Icons.verified, color: Colors.green),
          SizedBox(width: 8),
          Text('Phone verified'),
        ],
      );
    }

    final phone = client.phone;
    if (phone == null || phone.isEmpty) {
      return const Text(
        'Add the client’s phone number in step 1 before verifying.',
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('A code will be sent to ${_maskPhone(phone)}.'),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: _sending ? null : _send,
          icon: _sending
              ? const SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.sms),
          label: Text(_sent ? 'Resend code' : 'Send code'),
        ),
        if (_sent) ...[
          const SizedBox(height: 16),
          TextField(
            controller: _code,
            keyboardType: TextInputType.number,
            maxLength: 6,
            decoration: const InputDecoration(
              labelText: 'Verification code',
              border: OutlineInputBorder(),
              counterText: '',
            ),
          ),
          if (_expiresAt != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'Code expires around ${TimeOfDay.fromDateTime(_expiresAt!).format(context)}.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _verifying ? null : _verify,
            child: _verifying
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Verify'),
          ),
        ],
      ],
    );
  }
}
