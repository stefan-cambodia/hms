# Backup service: PostgreSQL client tools of the database's major version,
# plus jq to read requests from the administration screen and write status.
# Build context: deploy/.
FROM postgres:17-alpine
RUN apk add --no-cache jq
COPY scripts/backup-common.sh scripts/backup-service.sh scripts/backup-once.sh scripts/backup-restore.sh /scripts/
RUN chmod 0755 /scripts/*.sh
ENTRYPOINT ["/scripts/backup-service.sh"]
