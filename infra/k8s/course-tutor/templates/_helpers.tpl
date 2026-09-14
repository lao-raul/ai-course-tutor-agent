{{- define "course-tutor.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Fail closed for unsafe or contradictory storage/provider profiles. */}}
{{- define "course-tutor.validate" -}}
{{- if and .Values.courseContent.enabled .Values.fakeLlm.enabled -}}
{{- fail "courseContent.enabled and fakeLlm.enabled cannot both be true; use a real provider for local-real content" -}}
{{- end -}}
{{- if and .Values.courseContent.enabled (not .Values.courseContent.createPvc) (not .Values.courseContent.existingClaim) -}}
{{- fail "courseContent.existingClaim is required when course content is enabled and createPvc is false" -}}
{{- end -}}
{{- if and .Values.courseContent.enabled .Values.ciFixture.enabled -}}
{{- fail "courseContent.enabled and ciFixture.enabled cannot both be true" -}}
{{- end -}}
{{- end }}

{{- define "course-tutor.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "course-tutor.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "course-tutor.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
app.kubernetes.io/name: {{ include "course-tutor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}

{{- define "course-tutor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "course-tutor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "course-tutor.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "course-tutor.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "course-tutor.secretName" -}}
{{- default (printf "%s-runtime" (include "course-tutor.fullname" .)) .Values.secrets.existingSecret }}
{{- end }}

{{- define "course-tutor.image" -}}
{{- $image := index . 0 -}}
{{- if $image.digest -}}
{{ printf "%s@%s" $image.repository $image.digest }}
{{- else -}}
{{ printf "%s:%s" $image.repository $image.tag }}
{{- end -}}
{{- end }}

{{- define "course-tutor.commonEnv" -}}
- name: ENVIRONMENT
  value: {{ .Values.config.environment | quote }}
- name: LOG_LEVEL
  value: {{ .Values.config.logLevel | quote }}
- name: LOG_FORMAT
  value: {{ .Values.config.logFormat | quote }}
- name: AUTH_MODE
  value: {{ .Values.config.authMode | quote }}
- name: OIDC_ISSUER
  value: {{ .Values.config.oidcIssuer | quote }}
- name: OIDC_AUDIENCE
  value: {{ .Values.config.oidcAudience | quote }}
- name: OIDC_JWKS_URL
  value: {{ .Values.config.oidcJwksUrl | quote }}
- name: OIDC_ALGORITHMS
  value: {{ .Values.config.oidcAlgorithms | quote }}
- name: POSTGRES_DSN
  value: {{ .Values.config.postgresDsn | quote }}
- name: REDIS_URL
  value: {{ .Values.config.redisUrl | quote }}
- name: QDRANT_URL
  value: {{ .Values.config.qdrantUrl | quote }}
- name: MINIO_ENDPOINT
  value: {{ .Values.config.minioEndpoint | quote }}
- name: MINIO_BUCKET
  value: {{ .Values.config.minioBucket | quote }}
- name: LLM_BASE_URL
  value: {{ .Values.config.llmBaseUrl | quote }}
- name: LLM_CHAT_MODEL
  value: {{ .Values.config.llmChatModel | quote }}
- name: LLM_EMBEDDING_MODEL
  value: {{ .Values.config.llmEmbeddingModel | quote }}
- name: LLM_EMBEDDING_DIMENSION
  value: {{ .Values.config.llmEmbeddingDimension | quote }}
- name: MEMORY_EXTRACTION_INTERVAL
  value: {{ .Values.config.memoryExtractionInterval | quote }}
- name: CHAT_TURN_RETENTION_DAYS
  value: {{ .Values.config.chatTurnRetentionDays | quote }}
- name: SESSION_SUMMARY_RETENTION_DAYS
  value: {{ .Values.config.sessionSummaryRetentionDays | quote }}
- name: BUILD_VERSION
  value: {{ .Chart.AppVersion | quote }}
- name: BUILD_REVISION
  value: {{ default "unknown" .Values.global.buildRevision | quote }}
{{- if eq .Values.config.authMode "local" }}
- name: LOCAL_AUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "course-tutor.secretName" . }}
      key: local-auth-token
{{- end }}
- name: MINIO_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "course-tutor.secretName" . }}
      key: minio-access-key
- name: MINIO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "course-tutor.secretName" . }}
      key: minio-secret-key
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "course-tutor.secretName" . }}
      key: llm-api-key
{{- end }}
