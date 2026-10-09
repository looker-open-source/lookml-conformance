include: "/views/orders.view.lkml"
view: +orders {
  sql_table_name: analytics.orders_clean ;;
}
