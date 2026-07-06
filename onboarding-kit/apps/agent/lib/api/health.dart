import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config.dart';
import 'auth_interceptor.dart';

/// Health payload returned by `GET /api/v1/health`.
class HealthStatus {
  const HealthStatus({required this.status, required this.database});

  final String status;
  final String database;

  factory HealthStatus.fromJson(Map<String, dynamic> json) => HealthStatus(
        status: json['status'] as String? ?? 'unknown',
        database: json['database'] as String? ?? 'unknown',
      );

  bool get isHealthy => status == 'ok';
}

/// Shared dio client for all API calls.
///
/// It carries the [AuthInterceptor], which attaches the current access token to
/// every request and transparently refreshes it on a `401` (CLAUDE.md §7: access
/// tokens are short-lived and refresh tokens rotate). Auth endpoints and the
/// health check pass through untouched.
final dioProvider = Provider<Dio>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
    ),
  );
  dio.interceptors.add(AuthInterceptor(ref, dio.options));
  return dio;
});

/// Fetches the API health status. Used by the Phase 0 connectivity screen.
final healthProvider = FutureProvider<HealthStatus>((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get<Map<String, dynamic>>('/api/v1/health');
  return HealthStatus.fromJson(response.data ?? const {});
});
