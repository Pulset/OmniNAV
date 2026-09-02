from app.api.routes import (
    alerts,
    assets,
    health,
    market,
    metrics,
    portfolio,
    snapshots,
    transactions,
)

all_routers = [
    health.router,
    assets.router,
    transactions.router,
    market.router,
    portfolio.router,
    snapshots.router,
    alerts.router,
    metrics.router,
]
