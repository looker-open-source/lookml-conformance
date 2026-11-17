include: "/views/orders.view.lkml"
view: +orders {
  sql_table_name: scratch.orders_test ;;
}
