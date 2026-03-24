display_hot = pd.DataFrame({
    "Coin": hot["symbol"].str.upper(),
    "Price ($)": hot["current_price"].round(6),
    "1h %": hot["price_change_percentage_1h"].fillna(0).round(2) if "price_change_percentage_1h" in hot.columns else 0.0,
    "24h %": hot["price_change_percentage_24h"].round(2),
    "24h Volume": hot["total_volume"].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"),
    "Detected (Dubai)": dubai_tz.strftime("%H:%M:%S")
})