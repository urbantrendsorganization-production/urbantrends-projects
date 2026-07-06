import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/applications_repository.dart';
import '../api/models.dart';

/// Drives one application's onboarding flow: it owns the authoritative
/// [ApplicationDetail] (server truth) and exposes the step actions.
///
/// Mutating actions update state from the server's response and rethrow
/// [ApiException] on failure so the calling step can show an inline error and
/// offer retry — without wiping the loaded detail (no lost work, §12).
class OnboardingController
    extends FamilyAsyncNotifier<ApplicationDetail, String> {
  ApplicationsRepository get _repo =>
      ref.read(applicationsRepositoryProvider);

  @override
  Future<ApplicationDetail> build(String arg) => _repo.detail(arg);

  /// Re-fetch the detail (e.g. after a document finishes processing).
  Future<void> reload() async {
    state = await AsyncValue.guard(() => _repo.detail(arg));
  }

  /// Persist one section of client details and adopt the refreshed detail.
  Future<void> saveSection({
    String? fullName,
    String? phone,
    String? nationalIdNumber,
    String? kraPin,
    DateTime? dateOfBirth,
    String? address,
    Map<String, dynamic>? nextOfKin,
  }) async {
    final detail = await _repo.patch(
      arg,
      fullName: fullName,
      phone: phone,
      nationalIdNumber: nationalIdNumber,
      kraPin: kraPin,
      dateOfBirth: dateOfBirth,
      address: address,
      nextOfKin: nextOfKin,
    );
    state = AsyncData(detail);
  }

  /// Send an OTP to the client's phone (returns dev code only in dev, §8).
  Future<OtpSendResult> sendOtp() => _repo.sendOtp(arg);

  /// Verify the client's OTP, then reload so `otpVerified` reflects the change.
  Future<void> verifyOtp(String code) async {
    await _repo.verifyOtp(arg, code);
    await reload();
  }

  /// Record consent for the given terms version, then reload.
  Future<void> recordConsent(String termsVersion) async {
    await _repo.consent(id: arg, termsVersion: termsVersion, accepted: true);
    await reload();
  }

  /// Submit the application (completeness-validated server-side, §6).
  Future<ApplicationSummary> submit() async {
    final summary = await _repo.submit(arg);
    await reload();
    return summary;
  }
}

final onboardingControllerProvider = AsyncNotifierProvider.family<
    OnboardingController, ApplicationDetail, String>(OnboardingController.new);
