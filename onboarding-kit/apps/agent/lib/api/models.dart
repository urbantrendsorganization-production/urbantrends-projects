/// Dart mirrors of the backend onboarding DTOs (`routes/dto.rs`). These are
/// hand-written for the MVP; once the OpenAPI spec is wired the generated
/// dart-dio models replace this file (CLAUDE.md §7).
library;

/// The onboarding application status (backend `StatusKind`, snake_case wire
/// form). Unknown strings fall back to [unknown] so the app degrades instead of
/// crashing on a schema it doesn't recognize.
enum AppStatus {
  draft('draft', 'Draft'),
  submitted('submitted', 'Submitted'),
  underReview('under_review', 'Under review'),
  approved('approved', 'Approved'),
  rejected('rejected', 'Rejected'),
  returnedForCorrection('returned_for_correction', 'Returned'),
  unknown('unknown', 'Unknown');

  const AppStatus(this.wire, this.label);

  /// The exact string the backend serializes.
  final String wire;

  /// Short label for badges.
  final String label;

  static AppStatus fromWire(String? value) {
    for (final s in AppStatus.values) {
      if (s.wire == value) return s;
    }
    return AppStatus.unknown;
  }

  /// Editable by the agent again (Draft or Returned) — mirrors backend
  /// `load_owned_editable`.
  bool get isEditable =>
      this == AppStatus.draft || this == AppStatus.returnedForCorrection;

  /// Terminal states (Approved / Rejected, §6).
  bool get isTerminal =>
      this == AppStatus.approved || this == AppStatus.rejected;
}

/// A row in the applications queue (`ApplicationResponse`).
class ApplicationSummary {
  const ApplicationSummary({
    required this.id,
    required this.clientId,
    required this.productCode,
    required this.status,
    required this.otpVerified,
    required this.consentGiven,
    required this.consentTermsVersion,
    required this.submittedAt,
    required this.createdAt,
    required this.updatedAt,
  });

  final String id;
  final String clientId;
  final String productCode;
  final AppStatus status;
  final bool otpVerified;
  final bool consentGiven;
  final String? consentTermsVersion;
  final DateTime? submittedAt;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory ApplicationSummary.fromJson(Map<String, dynamic> json) =>
      ApplicationSummary(
        id: json['id'] as String? ?? '',
        clientId: json['client_id'] as String? ?? '',
        productCode: json['product_code'] as String? ?? '',
        status: AppStatus.fromWire(json['status'] as String?),
        otpVerified: json['otp_verified'] as bool? ?? false,
        consentGiven: json['consent_given'] as bool? ?? false,
        consentTermsVersion: json['consent_terms_version'] as String?,
        submittedAt: _dt(json['submitted_at']),
        createdAt: _dt(json['created_at']) ?? DateTime.now(),
        updatedAt: _dt(json['updated_at']) ?? DateTime.now(),
      );
}

/// The client shell attached to an application (`ClientResponse`).
class ClientModel {
  const ClientModel({
    required this.id,
    required this.fullName,
    this.phone,
    this.nationalIdNumber,
    this.kraPin,
    this.dateOfBirth,
    this.address,
    this.nextOfKin,
    this.clientNumber,
  });

  final String id;
  final String fullName;
  final String? phone;
  final String? nationalIdNumber;
  final String? kraPin;
  final DateTime? dateOfBirth;
  final String? address;
  final Map<String, dynamic>? nextOfKin;
  final String? clientNumber;

  factory ClientModel.fromJson(Map<String, dynamic> json) => ClientModel(
        id: json['id'] as String? ?? '',
        fullName: json['full_name'] as String? ?? '',
        phone: json['phone'] as String?,
        nationalIdNumber: json['national_id_number'] as String?,
        kraPin: json['kra_pin'] as String?,
        dateOfBirth: _dt(json['date_of_birth']),
        address: json['address'] as String?,
        nextOfKin: (json['next_of_kin'] as Map?)?.cast<String, dynamic>(),
        clientNumber: json['client_number'] as String?,
      );

  String? get nextOfKinName => nextOfKin?['name'] as String?;
  String? get nextOfKinPhone => nextOfKin?['phone'] as String?;
  String? get nextOfKinRelationship => nextOfKin?['relationship'] as String?;
}

/// A KYC document with its short-lived presigned GET URL (`DocumentResponse`).
class DocumentModel {
  const DocumentModel({
    required this.id,
    required this.docType,
    required this.processed,
    required this.url,
    this.thumbnailUrl,
  });

  final String id;
  final String docType;
  final bool processed;
  final String url;
  final String? thumbnailUrl;

  factory DocumentModel.fromJson(Map<String, dynamic> json) => DocumentModel(
        id: json['id'] as String? ?? '',
        docType: json['doc_type'] as String? ?? '',
        processed: json['processed'] as bool? ?? false,
        url: json['url'] as String? ?? '',
        thumbnailUrl: json['thumbnail_url'] as String?,
      );
}

/// A transition record (`EventResponse`). Reviewer notes/reasons ride the
/// `reason` field (§6).
class EventModel {
  const EventModel({
    required this.toStatus,
    required this.createdAt,
    this.fromStatus,
    this.reason,
  });

  final AppStatus toStatus;
  final AppStatus? fromStatus;
  final String? reason;
  final DateTime createdAt;

  factory EventModel.fromJson(Map<String, dynamic> json) => EventModel(
        toStatus: AppStatus.fromWire(json['to_status'] as String?),
        fromStatus: json['from_status'] == null
            ? null
            : AppStatus.fromWire(json['from_status'] as String?),
        reason: json['reason'] as String?,
        createdAt: _dt(json['created_at']) ?? DateTime.now(),
      );
}

/// Full application detail (`ApplicationDetailResponse`).
class ApplicationDetail {
  const ApplicationDetail({
    required this.application,
    required this.client,
    required this.documents,
    required this.events,
  });

  final ApplicationSummary application;
  final ClientModel client;
  final List<DocumentModel> documents;
  final List<EventModel> events;

  factory ApplicationDetail.fromJson(Map<String, dynamic> json) =>
      ApplicationDetail(
        application: ApplicationSummary.fromJson(
          (json['application'] as Map).cast<String, dynamic>(),
        ),
        client:
            ClientModel.fromJson((json['client'] as Map).cast<String, dynamic>()),
        documents: ((json['documents'] as List?) ?? const [])
            .map((e) => DocumentModel.fromJson((e as Map).cast<String, dynamic>()))
            .toList(),
        events: ((json['events'] as List?) ?? const [])
            .map((e) => EventModel.fromJson((e as Map).cast<String, dynamic>()))
            .toList(),
      );

  /// The processed document for a given type, if uploaded and ready.
  DocumentModel? documentFor(String docType) {
    for (final d in documents) {
      if (d.docType == docType) return d;
    }
    return null;
  }

  /// Reviewer notes to surface prominently on a returned application (§12): the
  /// most recent `-> returned_for_correction` event's reason.
  String? get reviewerNotes {
    for (final e in events.reversed) {
      if (e.toStatus == AppStatus.returnedForCorrection &&
          (e.reason?.trim().isNotEmpty ?? false)) {
        return e.reason!.trim();
      }
    }
    return null;
  }
}

/// A page of applications (`Paginated<ApplicationResponse>`).
class ApplicationsPage {
  const ApplicationsPage({
    required this.items,
    required this.page,
    required this.perPage,
    required this.total,
  });

  final List<ApplicationSummary> items;
  final int page;
  final int perPage;
  final int total;

  factory ApplicationsPage.fromJson(Map<String, dynamic> json) {
    final meta = (json['meta'] as Map?)?.cast<String, dynamic>() ?? const {};
    return ApplicationsPage(
      items: ((json['data'] as List?) ?? const [])
          .map((e) =>
              ApplicationSummary.fromJson((e as Map).cast<String, dynamic>()))
          .toList(),
      page: meta['page'] as int? ?? 1,
      perPage: meta['per_page'] as int? ?? 20,
      total: meta['total'] as int? ?? 0,
    );
  }
}

/// Result of presigning a document upload (`PresignResponse`).
class PresignResult {
  const PresignResult({required this.url, required this.storageKey});

  final String url;
  final String storageKey;

  factory PresignResult.fromJson(Map<String, dynamic> json) => PresignResult(
        url: json['url'] as String? ?? '',
        storageKey: json['storage_key'] as String? ?? '',
      );
}

/// Result of sending a client OTP (`SendResponse`). [devCode] is only present in
/// dev when `DEV_EXPOSE_OTP=true` (§8) and must never be shown in production.
class OtpSendResult {
  const OtpSendResult({required this.expiresAt, this.devCode});

  final DateTime? expiresAt;
  final String? devCode;

  factory OtpSendResult.fromJson(Map<String, dynamic> json) => OtpSendResult(
        expiresAt: _dt(json['expires_at']),
        devCode: json['dev_code'] as String?,
      );
}

DateTime? _dt(Object? value) {
  if (value is String && value.isNotEmpty) {
    return DateTime.tryParse(value)?.toLocal();
  }
  return null;
}
