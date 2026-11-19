from app.api.routes import (
    admin,
    advice,
    alerts,
    assets,
    auth,
    chat,
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
    advice.router,
    chat.router,
]
