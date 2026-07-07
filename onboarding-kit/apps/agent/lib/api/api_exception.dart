import 'package:dio/dio.dart';

/// A user-safe API failure carrying the backend error envelope
/// (`{ "error": { "code", "message" } }`, CLAUDE.md §7) or a friendly message
/// for transport failures (offline / timeout).
class ApiException implements Exception {
  const ApiException({
    required this.message,
    this.code,
    this.statusCode,
    this.isNetwork = false,
  });

  /// Human-readable, safe to show to the agent.
  final String message;

  /// Machine code from the backend envelope (e.g. `validation_error`), if any.
  final String? code;

  /// HTTP status, if the request reached the server.
  final int? statusCode;

  /// True when the request never got a response (no connectivity, timeout).
  final bool isNetwork;

  /// Build an [ApiException] from a Dio failure, preferring the backend's
  /// structured error body and degrading gracefully for offline states.
  factory ApiException.from(Object error) {
    if (error is ApiException) return error;
    if (error is! DioException) {
      return const ApiException(message: 'Something went wrong. Please retry.');
    }

    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.transformTimeout:
      case DioExceptionType.connectionError:
        return const ApiException(
          message:
              'Can’t reach the server. Check your connection and try again.',
          isNetwork: true,
        );
      case DioExceptionType.cancel:
        return const ApiException(message: 'Request cancelled.');
      case DioExceptionType.badCertificate:
        return const ApiException(message: 'Secure connection failed.');
      case DioExceptionType.badResponse:
      case DioExceptionType.unknown:
        break;
    }

    final response = error.response;
    if (response == null) {
      return const ApiException(
        message:
            'Can’t reach the server. Check your connection and try again.',
        isNetwork: true,
      );
    }

    final data = response.data;
    if (data is Map && data['error'] is Map) {
      final body = data['error'] as Map;
      return ApiException(
        message: (body['message'] as String?)?.trim().isNotEmpty == true
            ? body['message'] as String
            : 'Request failed. Please try again.',
        code: body['code'] as String?,
        statusCode: response.statusCode,
      );
    }

    return ApiException(
      message: 'Request failed (${response.statusCode}). Please try again.',
      statusCode: response.statusCode,
    );
  }
}
