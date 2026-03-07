"""
Load Testing for Third Place Platform using Locust

Usage:
    # Install locust
    pip install locust
    
    # Run load test
    locust -f tests/load_test.py --host=http://localhost:8000
    
    # Run with specific settings
    locust -f tests/load_test.py --host=http://localhost:8000 --users 100 --spawn-rate 10
    
    # Run headless (no web UI)
    locust -f tests/load_test.py --host=http://localhost:8000 --headless --users 100 --spawn-rate 10 --run-time 5m
    
    # View results at http://localhost:8089
"""
from locust import HttpUser, task, between, events
import json
import logging
import random
import string

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ThirdPlaceUser(HttpUser):
    """
    Simulated user for load testing the Third Place Platform
    
    Behaviors:
    - Login and obtain token
    - View envelopes
    - Classify activities
    - Get pricing quotes
    - View health checks
    """
    
    # Wait 1-3 seconds between tasks
    wait_time = between(1, 3)
    
    # Test data
    test_username = "loadtestuser"
    test_password = "LoadTest123!"
    test_email = "loadtest@example.com"
    
    # Store auth token
    access_token = None
    
    def on_start(self):
        """Called when a simulated user starts"""
        # Try to login with existing test user
        self.login()
    
    def login(self):
        """Login and store access token"""
        try:
            # First try to login
            response = self.client.post(
                "/api/v1/auth/login",
                json={
                    "username": self.test_username,
                    "password": self.test_password
                }
            )
            
            if response.status_code == 401:
                # User doesn't exist, create it
                self.register()
                # Try login again
                response = self.client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": self.test_username,
                        "password": self.test_password
                    }
                )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("access_token")
                logger.info(f"User {self.test_username} logged in successfully")
            else:
                logger.warning(f"Login failed: {response.status_code}")
                self.access_token = None
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            self.access_token = None
    
    def register(self):
        """Register a new test user"""
        try:
            response = self.client.post(
                "/api/v1/auth/register",
                json={
                    "username": self.test_username,
                    "email": self.test_email,
                    "password": self.test_password,
                    "role": "participant"
                }
            )
            if response.status_code in [201, 400]:
                logger.info(f"User registration: {response.status_code}")
        except Exception as e:
            logger.error(f"Registration error: {e}")
    
    def get_headers(self):
        """Get headers with auth token"""
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}
    
    @task(10)
    def health_check(self):
        """Check health endpoint (most common operation)"""
        self.client.get("/health")
    
    @task(5)
    def detailed_health_check(self):
        """Check detailed health endpoint"""
        self.client.get("/health/detailed")
    
    @task(8)
    def classify_activity(self):
        """Classify an activity"""
        activities = [
            "board games",
            "yoga class",
            "book club meeting",
            "cooking workshop",
            "discussion group"
        ]
        
        self.client.post(
            "/api/v1/ial/activity/classify",
            json={
                "space_id": "test-space-001",
                "declared_activity": random.choice(activities),
                "attendance_cap": random.randint(5, 50)
            },
            headers=self.get_headers()
        )
    
    @task(6)
    def get_pricing_quote(self):
        """Get insurance pricing quote"""
        self.client.post(
            "/api/v1/ial/pricing/quote",
            json={
                "activity_class_id": "passive-class-id",
                "space_id": "test-space-001",
                "attendance_cap": random.randint(10, 100),
                "duration_minutes": random.choice([60, 120, 180, 240]),
                "jurisdiction": "US-CA"
            },
            headers=self.get_headers()
        )
    
    @task(4)
    def list_envelopes(self):
        """List insurance envelopes"""
        self.client.get(
            "/api/v1/ial/envelopes?limit=20",
            headers=self.get_headers()
        )
    
    @task(3)
    def get_activity_classes(self):
        """Get available activity classes"""
        self.client.get(
            "/api/v1/ial/activity-classes",
            headers=self.get_headers()
        )
    
    @task(2)
    def get_current_user(self):
        """Get current user info"""
        self.client.get(
            "/api/v1/auth/me",
            headers=self.get_headers()
        )
    
    @task(1)
    def rate_limit_info(self):
        """Get rate limit information"""
        self.client.get("/rate-limit-info")


class AdminUser(HttpUser):
    """
    Simulated admin user for load testing admin operations
    
    Behaviors:
    - View audit logs
    - List all users
    - View system metrics
    """
    
    wait_time = between(2, 5)
    
    admin_username = "admin"
    admin_password = "Admin123!"
    access_token = None
    
    def on_start(self):
        """Login as admin"""
        try:
            response = self.client.post(
                "/api/v1/auth/login",
                json={
                    "username": self.admin_username,
                    "password": self.admin_password
                }
            )
            
            if response.status_code == 200:
                self.access_token = response.json().get("access_token")
                logger.info("Admin logged in successfully")
        except Exception as e:
            logger.error(f"Admin login error: {e}")
    
    @task(5)
    def view_audit_logs(self):
        """View audit logs"""
        self.client.get(
            "/api/v1/audit/logs?limit=50",
            headers={"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        )
    
    @task(3)
    def view_audit_summary(self):
        """View audit log summary"""
        self.client.get(
            "/api/v1/audit/logs/summary?hours=24",
            headers={"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        )
    
    @task(2)
    def list_users(self):
        """List all users"""
        self.client.get(
            "/api/v1/auth/users?limit=50",
            headers={"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        )


# =============================================================================
# Event Handlers
# =============================================================================

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when load test starts"""
    logger.info("=" * 60)
    logger.info("Load Test Starting")
    logger.info(f"Target: {environment.host}")
    logger.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when load test stops"""
    logger.info("=" * 60)
    logger.info("Load Test Complete")
    
    # Print summary
    stats = environment.stats
    logger.info(f"Total Requests: {stats.total.num_requests}")
    logger.info(f"Total Failures: {stats.total.num_failures}")
    logger.info(f"Failure Rate: {stats.total.fail_ratio * 100:.2f}%")
    logger.info(f"Average Response Time: {stats.total.avg_response_time:.2f}ms")
    logger.info(f"Requests/sec: {stats.total.current_rps:.2f}")
    logger.info("=" * 60)


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Called on each request"""
    if exception:
        logger.warning(f"Request failed: {name} - {exception}")
    
    if response_time > 1000:
        logger.warning(f"Slow request: {name} took {response_time:.2f}ms")


# =============================================================================
# Test Configuration
# =============================================================================

if __name__ == "__main__":
    import os
    
    # Default configuration
    HOST = os.getenv("LOCUST_HOST", "http://localhost:8000")
    USERS = int(os.getenv("LOCUST_USERS", "50"))
    SPAWN_RATE = int(os.getenv("LOCUST_SPAWN_RATE", "10"))
    RUN_TIME = os.getenv("LOCUST_RUN_TIME", "5m")
    
    print(f"""
    Load Test Configuration:
    - Host: {HOST}
    - Users: {USERS}
    - Spawn Rate: {SPAWN_RATE}/s
    - Run Time: {RUN_TIME}
    
    Run with:
    locust -f tests/load_test.py --host={HOST} --headless --users={USERS} --spawn-rate={SPAWN_RATE} --run-time={RUN_TIME}
    """)
