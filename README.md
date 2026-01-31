# Third Place Platform

The Third Place Platform is a comprehensive solution for managing recurring physical community spaces with integrated insurance and access control. This platform enables communities to safely and efficiently organize physical gatherings by providing insurance coverage and access control mechanisms.

## Architecture Overview

The platform consists of several key components:

### 1. Insurance Abstraction Layer (IAL)
- **Insurance Envelope**: The atomic unit of coverage that wraps physical gatherings
- **Activity Classification Engine (ACE)**: Classifies activities and determines risk profiles
- **Pricing Engine**: Calculates insurance costs based on risk factors
- **Policy Management**: Manages master policies and coverage limits

### 2. Access Control System
- **Lock Integration**: Supports multiple lock vendors (Kisi, Schlage, generic QR)
- **Access Grants**: Short-lived permissions derived from insurance envelopes
- **Capacity Enforcement**: Ensures attendance limits are not exceeded
- **Real-time Enforcement**: Automatically revokes access when insurance is voided

### 3. Claims and Incident Management
- **Incident Reporting**: Pre-claim signal tracking
- **Claims Processing**: Formal insurance claim handling
- **Risk Analysis**: Pattern analysis for improving risk assessment

### 4. Security and Authentication
- **Role-based Access Control**: Admin, platform operator, space owner, steward roles
- **JWT Authentication**: Secure token-based authentication
- **Fine-grained Permissions**: Resource-level access controls

## Key Features

### Insurance as a Service
- Automated insurance coverage for physical gatherings
- Risk-based pricing with multiple factors (activity type, attendance, duration, location)
- Real-time policy enforcement tied to physical access

### Access Control Integration
- Tight coupling between insurance status and physical access
- Automatic revocation when insurance is voided
- Capacity enforcement to prevent overcrowding

### Community-Centric Design
- Focus on recurring, non-commercial gatherings
- Low-friction setup for community organizers
- Support for diverse activity types

## Technical Stack

- **Framework**: FastAPI for high-performance API
- **Database**: SQLAlchemy with PostgreSQL support
- **Authentication**: JWT with role-based access control
- **Lock Integration**: Adapters for multiple lock vendors
- **Testing**: PyTest for comprehensive test coverage

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and configure your settings
4. Initialize the database:
   ```bash
   python init_db.py
   ```
5. Run the application:
   ```bash
   uvicorn main:app --reload
   ```

## API Endpoints

### Insurance Abstraction Layer
- `POST /api/v1/ial/activity/classify` - Classify an activity and determine risk
- `POST /api/v1/ial/pricing/quote` - Get insurance pricing quote
- `POST /api/v1/ial/envelopes` - Create insurance envelope
- `GET /api/v1/ial/envelopes/{id}/verify` - Verify coverage
- `POST /api/v1/ial/envelopes/{id}/void` - Void insurance envelope

### Health Check
- `GET /health` - Application health status

## Security Considerations

- All endpoints require authentication except health checks
- Insurance status is tightly coupled with physical access
- Automatic revocation mechanisms for security incidents
- Rate limiting and access pattern monitoring

## Deployment

For production deployment:
1. Use a production-grade database (PostgreSQL recommended)
2. Configure proper SSL certificates
3. Set up proper logging and monitoring
4. Implement backup strategies
5. Use environment-specific configurations

## Contributing

Contributions are welcome! Please follow these steps:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.