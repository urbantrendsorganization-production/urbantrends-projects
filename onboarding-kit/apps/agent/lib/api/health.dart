import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config.dart';

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

/// Shared dio client. In Phase 2 this is replaced by the generated OpenAPI
/// dart-dio client and gains auth interceptors.
final dioProvider = Provider<Dio>((ref) {
  return Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 5),
    ),
  );
});

/// Fetches the API health status. Used by the Phase 0 connectivity screen.
final healthProvider = FutureProvider<HealthStatus>((ref) async {
  final dio = ref.watch(dioProvider);
  final response = await dio.get<Map<String, dynamic>>('/api/v1/health');
  return HealthStatus.fromJson(response.data ?? const {});
});
