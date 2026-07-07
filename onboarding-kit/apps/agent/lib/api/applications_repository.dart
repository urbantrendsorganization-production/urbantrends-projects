import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config.dart' show ProductOption;
import 'api_exception.dart';
import 'health.dart' show dioProvider;
import 'models.dart';

/// The four required KYC document types, in capture order (backend
/// `REQUIRED_DOC_TYPES`, §6/§7). address_proof also accepts PDF server-side.
const List<String> kRequiredDocTypes = [
  'id_front',
  'id_back',
  'selfie',
  'address_proof',
];

/// Coerce a Dio response body into a JSON map. Responses are requested untyped
/// (`<dynamic>`) so the auth interceptor's refresh-retry — which resolves a
/// `Response<dynamic>` — never trips a generic cast.
Map<String, dynamic> _map(Response<dynamic> res) {
  final data = res.data;
  return data is Map ? data.cast<String, dynamic>() : const {};
}

/// Talks to the onboarding endpoints (§7). All calls normalize failures into
/// [ApiException] so the UI can render safe messages and offer retry.
class ApplicationsRepository {
  ApplicationsRepository(this._dio);

  final Dio _dio;

  /// Bare client for uploading directly to the presigned object-storage URL.
  /// It must NOT carry our API auth header or base URL (§11: the client PUTs
  /// straight to storage).
  final Dio _uploader = Dio();

  // ---- Queue ---------------------------------------------------------------

  /// `GET /applications` — the agent's own applications (role-scoped server
  /// side). Fetches a large page; the MVP agent load is small.
  Future<ApplicationsPage> list({int page = 1, int perPage = 100}) async {
    try {
      final res = await _dio.get<dynamic>(
        '/api/v1/applications',
        queryParameters: {'page': page, 'per_page': perPage},
      );
      return ApplicationsPage.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// `GET /applications/:id` — full detail with presigned document URLs.
  Future<ApplicationDetail> detail(String id) async {
    try {
      final res = await _dio.get<dynamic>('/api/v1/applications/$id');
      return ApplicationDetail.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// `GET /products` — the tenant's active products, so the agent picks a
  /// real `product_code` (admin-managed) instead of a hardcoded list. Inactive
  /// products are filtered out here.
  Future<List<ProductOption>> listProducts() async {
    try {
      final res = await _dio.get<dynamic>('/api/v1/products');
      final data = res.data;
      final list = data is List ? data : const [];
      return [
        for (final item in list)
          if (item is Map && item['is_active'] == true)
            ProductOption(
              code: (item['code'] ?? '').toString(),
              name: (item['name'] ?? '').toString(),
            ),
      ];
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  // ---- Create --------------------------------------------------------------

  /// `POST /clients` — create the client shell (name only), then the caller
  /// creates the draft application against it.
  Future<ClientModel> createClient(String fullName) async {
    try {
      final res = await _dio.post<dynamic>(
        '/api/v1/clients',
        data: {'full_name': fullName},
      );
      return ClientModel.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// `POST /applications` — open a Draft for a client under a product.
  Future<ApplicationSummary> createApplication({
    required String clientId,
    required String productCode,
  }) async {
    try {
      final res = await _dio.post<dynamic>(
        '/api/v1/applications',
        data: {'client_id': clientId, 'product_code': productCode},
      );
      return ApplicationSummary.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  // ---- Progressive save ----------------------------------------------------

  /// `PATCH /applications/:id` — persist one section of client details. Only
  /// the supplied (non-null) fields are sent, so a dropped connection never
  /// loses previously saved sections (§12). Returns the refreshed detail.
  Future<ApplicationDetail> patch(
    String id, {
    String? fullName,
    String? phone,
    String? nationalIdNumber,
    String? kraPin,
    DateTime? dateOfBirth,
    String? address,
    Map<String, dynamic>? nextOfKin,
  }) async {
    final body = <String, dynamic>{};
    if (fullName != null) body['full_name'] = fullName;
    if (phone != null) body['phone'] = phone;
    if (nationalIdNumber != null) body['national_id_number'] = nationalIdNumber;
    if (kraPin != null) body['kra_pin'] = kraPin;
    if (dateOfBirth != null) {
      // Backend expects a NaiveDate (YYYY-MM-DD).
      body['date_of_birth'] = dateOfBirth.toIso8601String().split('T').first;
    }
    if (address != null) body['address'] = address;
    if (nextOfKin != null) body['next_of_kin'] = nextOfKin;

    try {
      final res = await _dio.patch<dynamic>(
        '/api/v1/applications/$id',
        data: body,
      );
      return ApplicationDetail.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  // ---- Documents -----------------------------------------------------------

  /// `POST /applications/:id/documents/presign` — get a short-lived PUT URL.
  Future<PresignResult> presign({
    required String id,
    required String docType,
    required String contentType,
  }) async {
    try {
      final res = await _dio.post<dynamic>(
        '/api/v1/applications/$id/documents/presign',
        data: {'doc_type': docType, 'content_type': contentType},
      );
      return PresignResult.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// PUT the compressed bytes straight to object storage. The content type must
  /// match the value pinned into the presign signature (§11).
  Future<void> uploadToStorage({
    required String url,
    required Uint8List bytes,
    required String contentType,
    ProgressCallback? onProgress,
  }) async {
    try {
      await _uploader.put<void>(
        url,
        data: Stream.fromIterable([bytes]),
        onSendProgress: onProgress,
        options: Options(
          headers: {
            'Content-Type': contentType,
            Headers.contentLengthHeader: bytes.length,
          },
        ),
      );
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// `POST /applications/:id/documents/confirm` — validate + record the upload
  /// and enqueue the `process_image` job.
  Future<void> confirm({
    required String id,
    required String docType,
    required String storageKey,
    required String originalFilename,
  }) async {
    try {
      await _dio.post<dynamic>(
        '/api/v1/applications/$id/documents/confirm',
        data: {
          'doc_type': docType,
          'storage_key': storageKey,
          'original_filename': originalFilename,
        },
      );
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  // ---- OTP -----------------------------------------------------------------

  /// `POST /applications/:id/otp/send` — OTP to the CLIENT's phone (§8).
  Future<OtpSendResult> sendOtp(String id) async {
    try {
      final res =
          await _dio.post<dynamic>('/api/v1/applications/$id/otp/send');
      return OtpSendResult.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// `POST /applications/:id/otp/verify` — verify the code the client received.
  Future<void> verifyOtp(String id, String code) async {
    try {
      await _dio.post<dynamic>(
        '/api/v1/applications/$id/otp/verify',
        data: {'code': code},
      );
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  // ---- Consent + submit ----------------------------------------------------

  /// `POST /applications/:id/consent` — record acceptance of a terms version.
  Future<void> consent({
    required String id,
    required String termsVersion,
    required bool accepted,
  }) async {
    try {
      await _dio.post<dynamic>(
        '/api/v1/applications/$id/consent',
        data: {'terms_version': termsVersion, 'accepted': accepted},
      );
    } catch (e) {
      throw ApiException.from(e);
    }
  }

  /// `POST /applications/:id/submit` — completeness-validated transition to
  /// Submitted (§6). Returns the updated summary.
  Future<ApplicationSummary> submit(String id) async {
    try {
      final res =
          await _dio.post<dynamic>('/api/v1/applications/$id/submit');
      return ApplicationSummary.fromJson(_map(res));
    } catch (e) {
      throw ApiException.from(e);
    }
  }
}

final applicationsRepositoryProvider = Provider<ApplicationsRepository>((ref) {
  return ApplicationsRepository(ref.watch(dioProvider));
});

/// The tenant's active products, fetched from the backend (admin-managed). The
/// new-client dialog watches this so admin-added products appear in the app.
final productsProvider = FutureProvider<List<ProductOption>>((ref) {
  return ref.watch(applicationsRepositoryProvider).listProducts();
});
