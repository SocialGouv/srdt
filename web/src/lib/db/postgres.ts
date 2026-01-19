import postgres, { type Sql } from "postgres";

if (!process.env.DATABASE_URL) {
  throw new Error(
    'DATABASE_URL environment variable is required. Please set it in your .env file.'
  );
}

// PostgreSQL connection singleton
// Uses DATABASE_URL environment variable
const sql = postgres(process.env.DATABASE_URL, {
  max: 10, // Connection pool size
  idle_timeout: 30,
  connect_timeout: 10,
});

export default sql;
export type { Sql };
