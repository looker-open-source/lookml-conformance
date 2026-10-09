connection: "wh"
include: "/*.view"
explore: buyer_orders {
  from: orders
  join: buyer {
    from: users
    sql_on: ${buyer_orders.user_id} = ${buyer.id} ;;
    relationship: many_to_one
  }
}
