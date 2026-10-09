connection: "wh"
include: "/views/*.view.lkml"
explore: orders {
  join: users {
    sql_on: ${orders.user_id} = ${users.id} ;;
    relationship: many_to_one
  }
}
