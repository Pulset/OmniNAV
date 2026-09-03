from app.api.routes import (
    admin,
    alerts,
    assets,
    auth,
    health,
    market,
    metrics,
    portfolio,
    snapshots,
    transactions,
)

all_routers = [
    health.router,
    auth.router,
    admin.router,
    assets.router,
    transactions.router,
    market.router,
    portfolio.router,
    snapshots.router,
    alerts.router,
    metrics.router,
]
