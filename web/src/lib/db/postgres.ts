import postgres from "postgres";

// PostgreSQL connection singleton
// Uses DATABASE_URL environment variable
const sql = postgres(process.env.DATABASE_URL!, {
  max: 10, // Connection pool size
  idle_timeout: 30,
  connect_timeout: 10,
});

export default sql;
