# Third Place Platform - Operations Runbook

**Version:** 2.2.0
**Last Updated:** March 5, 2026
**Classification:** Internal Operations

---

## Quick Reference

| Service | Port | Health Check | Logs |
|---------|------|--------------|------|
| API Server | 8000 | `/health` | `/logs/app.log` |
| Prometheus Metrics | 8000 | `/metrics` | N/A |
| Redis (optional) | 6379 | `redis-cli ping` | N/A |
| PostgreSQL (optional) | 5432 | `pg_isready` | `/var/log/postgresql` |

### Emergency Contacts
- **On-Call Engineer:** [TODO: Add contact]
- **Platform Lead:** [TODO: Add contact]
- **Security Team:** [TODO: Add contact]

---

## 1. Deployment Procedures

### 1.1 Pre-Deployment Checklist

- [ ] All tests passing (`pytest tests/ -v`)
- [ ] Security scan clean (`bandit -r .`)
- [ ] Database migrations ready (`alembic current`)
- [ ] Backup created (if production)
- [ ] Rollback plan documented
- [ ] Stakeholders notified (if production)

### 1.2 Standard Deployment

```bash
# 1. Pull latest code
git pull origin main

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run database migrations
alembic upgrade head

# 4. Verify configuration
python -c "from config.configuration import validate_configuration; validate_configuration()"

# 5. Restart service
sudo systemctl restart thirdplace

# 6. Verify health
curl http://localhost:8000/health
curl http://localhost:8000/health/detailed

# 7. Check logs
tail -f /logs/app.log
```

### 1.3 Docker Deployment

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f api

# Run migrations
docker-compose exec api alembic upgrade head

# Health check
docker-compose exec api curl http://localhost:8000/health
```

### 1.4 Rollback Procedure

```bash
# 1. Stop accepting traffic (if behind load balancer)

# 2. Rollback database
alembic downgrade -1

# 3. Deploy previous version
git checkout <previous-tag>
pip install -r requirements.txt
sudo systemctl restart thirdplace

# 4. Verify rollback
curl http://localhost:8000/health

# 5. Notify stakeholders
```

---

## 2. Monitoring

### 2.1 Key Metrics

| Metric | Warning | Critical | Description |
|--------|---------|----------|-------------|
| Request Latency (p95) | >500ms | >2000ms | API response time |
| Error Rate | >1% | >5% | 5xx error percentage |
| Active Envelopes | - | - | Current active insurance envelopes |
| Cache Hit Rate | <80% | <50% | Redis cache effectiveness |
| Database Connections | >80% | >95% | Connection pool usage |
| Queue Depth | >100 | >500 | Background job queue |

### 2.2 Prometheus Queries

```promql
# Request rate
rate(http_requests_total[5m])

# Error rate
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])

# p95 latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Active envelopes
envelopes_active

# Cache hit rate
rate(cache_operations_total{result="hit"}[5m]) / rate(cache_operations_total[5m])
```

### 2.3 Log Queries

```bash
# Recent errors
grep "ERROR\|CRITICAL" /logs/app.log | tail -50

# Authentication failures
grep "Failed login" /logs/app.log | tail -20

# Rate limit hits
grep "Rate limit exceeded" /logs/app.log | tail -20

# Slow queries (>1s)
grep "took [1-9][0-9]\{3,\}ms" /logs/app.log
```

---

## 3. Incident Response

### 3.1 Service Unavailable

**Symptoms:**
- Health check failing
- 502/503 errors
- Connection refused

**Diagnosis:**
```bash
# Check service status
sudo systemctl status thirdplace

# Check logs
tail -100 /logs/app.log | grep -i error

# Check port
netstat -tlnp | grep 8000

# Check disk space
df -h

# Check memory
free -m
```

**Resolution:**
```bash
# Restart service
sudo systemctl restart thirdplace

# If still failing, check configuration
python -c "from config.configuration import validate_configuration; validate_configuration()"

# Check database connectivity
python -c "from config.database import engine; engine.connect()"
```

### 3.2 High Error Rate

**Symptoms:**
- Increased 5xx responses
- Exception logs
- User complaints

**Diagnosis:**
```bash
# Check recent errors
tail -200 /logs/app.log | grep ERROR

# Check exception types
grep "Exception\|Error" /logs/app.log | sort | uniq -c | sort -rn | head -10

# Check metrics
curl http://localhost:8000/metrics | grep exceptions
```

**Resolution:**
1. Identify error pattern from logs
2. Check recent deployments
3. Consider rollback if deployment-related
4. Fix and redeploy if code-related

### 3.3 Database Connection Issues

**Symptoms:**
- Slow responses
- Connection timeout errors
- "Too many connections" errors

**Diagnosis:**
```bash
# Check database status
docker-compose exec db pg_isready  # Docker
sudo systemctl status postgresql   # Native

# Check connection count
docker-compose exec db psql -U thirdplace -c "SELECT count(*) FROM pg_stat_activity;"

# Check slow queries
docker-compose exec db psql -U thirdplace -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"
```

**Resolution:**
```bash
# Restart database (Docker)
docker-compose restart db

# Or restart service to release connections
sudo systemctl restart thirdplace

# If persistent, increase pool size in .env
# DB_POOL_SIZE=10
# DB_MAX_OVERFLOW=20
```

### 3.4 Cache Issues

**Symptoms:**
- Slow responses
- Cache miss errors
- Redis connection errors

**Diagnosis:**
```bash
# Check Redis status
redis-cli ping

# Check Redis memory
redis-cli INFO memory

# Check cache stats
curl http://localhost:8000/metrics | grep cache
```

**Resolution:**
```bash
# Restart Redis
docker-compose restart redis  # Docker
sudo systemctl restart redis  # Native

# Clear cache if corrupted
redis-cli FLUSHDB

# Verify cache service
python -c "from services.cache_service import cache; print(cache.get_stats())"
```

### 3.5 Rate Limiting Triggered

**Symptoms:**
- 429 Too Many Requests
- Users unable to access API
- Rate limit metrics high

**Diagnosis:**
```bash
# Check rate limit metrics
curl http://localhost:8000/metrics | grep rate_limit

# Check logs for patterns
grep "Rate limit exceeded" /logs/app.log | tail -50

# Identify top IPs
grep "Rate limit exceeded" /logs/app.log | awk '{print $NF}' | sort | uniq -c | sort -rn | head -10
```

**Resolution:**
1. If legitimate traffic: Consider increasing limits temporarily
2. If attack: Implement IP blocking at firewall level
3. If single user: Contact user about usage patterns

---

## 4. Maintenance Procedures

### 4.1 Database Backup

```bash
# SQLite backup
cp /data/thirdplace.db /backups/thirdplace-$(date +%Y%m%d-%H%M%S).db

# PostgreSQL backup
docker-compose exec db pg_dump -U thirdplace thirdplace > /backups/thirdplace-$(date +%Y%m%d-%H%M%S).sql

# Verify backup
ls -lh /backups/
```

### 4.2 Database Restore

```bash
# SQLite restore
cp /backups/thirdplace-YYYYMMDD-HHMMSS.db /data/thirdplace.db
sudo systemctl restart thirdplace

# PostgreSQL restore
cat /backups/thirdplace-YYYYMMDD-HHMMSS.sql | docker-compose exec -T db psql -U thirdplace thirdplace
sudo systemctl restart thirdplace
```

### 4.3 Log Rotation

```bash
# Manual log rotation
mv /logs/app.log /logs/app.log.$(date +%Y%m%d)
kill -USR1 $(cat /var/run/thirdplace.pid)

# Or use logrotate
sudo logrotate /etc/logrotate.d/thirdplace
```

### 4.4 Cache Cleanup

```bash
# Clear all cache (use with caution!)
redis-cli FLUSHDB

# Clear specific pattern
redis-cli --scan --pattern "envelope:*" | xargs redis-cli DEL

# Verify cache size
redis-cli DBSIZE
```

---

## 5. Security Procedures

### 5.1 JWT Secret Rotation

```bash
# 1. Generate new secret
NEW_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

# 2. Update environment
export JWT_SECRET_KEY=$NEW_SECRET

# 3. Restart service (all instances simultaneously)
sudo systemctl restart thirdplace

# 4. Verify
curl http://localhost:8000/health/detailed

# Note: All existing tokens will be invalidated
```

### 5.2 Emergency Token Revocation

```bash
# Revoke all refresh tokens for a user
python -c "
from config.database import SessionLocal
from services.auth_service import AuthService
db = SessionLocal()
auth = AuthService(db)
count = auth.revoke_all_user_tokens('USER_ID')
print(f'Revoked {count} tokens')
"

# Or via API (if endpoint exists)
curl -X POST http://localhost:8000/api/v1/auth/emergency-revoke-tokens \
  -H "Authorization: Bearer $TOKEN"
```

### 5.3 Security Patch Deployment

```bash
# 1. Review security advisory
# 2. Test in staging
# 3. Deploy to production
pip install --upgrade <package>
alembic upgrade head
sudo systemctl restart thirdplace

# 4. Verify no regressions
curl http://localhost:8000/health/detailed
pytest tests/test_security.py -v
```

---

## 6. Performance Tuning

### 6.1 Connection Pool Tuning

```bash
# Current settings
echo $DB_POOL_SIZE
echo $DB_MAX_OVERFLOW

# Recommended for production
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
```

### 6.2 Cache Tuning

```bash
# Monitor cache hit rate
curl http://localhost:8000/metrics | grep cache_operations

# Adjust TTLs in services/cache_service.py if needed
# Default: 5 minutes
# High-traffic data: 10 minutes
# Volatile data: 2 minutes
```

### 6.3 Query Optimization

```bash
# Enable query logging
export SQL_ECHO=true

# Check for N+1 queries in logs
grep "SELECT" /logs/app.log | sort | uniq -c | sort -rn | head -20

# Add indexes for slow queries
# (Use Alembic migration)
```

---

## 7. Troubleshooting Guide

### Common Issues

| Issue | Symptoms | Solution |
|-------|----------|----------|
| Service won't start | Port in use | `lsof -i :8000` then `kill <PID>` |
| Database locked | SQLite errors | Check for zombie processes, enable WAL mode |
| Memory leak | Increasing memory | Check for unclosed sessions, restart service |
| Slow responses | High latency | Check cache hit rate, database queries |
| Auth failures | 401 errors | Check JWT secret, token expiration |

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
export SQL_ECHO=true

# Restart service
sudo systemctl restart thirdplace

# Check detailed logs
tail -f /logs/app.log
```

---

## 8. Contact Information

### Team Contacts
- **Platform Lead:** [Name] - [Email/Phone]
- **On-Call:** [Rotation Schedule]
- **Security:** [Security Team Contact]

### External Resources
- **Documentation:** `/docs` endpoint
- **API Swagger:** http://localhost:8000/docs
- **Metrics:** http://localhost:8000/metrics
- **GitHub:** [Repository URL]

---

*Last reviewed: March 5, 2026*
*Next review: April 5, 2026*
