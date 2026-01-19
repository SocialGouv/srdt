import postgres from "postgres";

// PostgreSQL connection singleton
// Returns null if DATABASE_URL is not configured
let sql: ReturnType<typeof postgres> | null = null;

if (process.env.DATABASE_URL) {
  try {
    sql = postgres(process.env.DATABASE_URL, {
      max: 10, // Connection pool size
      idle_timeout: 30,
      connect_timeout: 10,
      onnotice: () => {}, // Suppress PostgreSQL NOTICE messages
    });
  } catch (error) {
    console.warn("[database] Failed to create PostgreSQL connection:", error);
  }
} else {
  console.warn(
    "[database] DATABASE_URL not set - database features will be disabled"
  );
}

export default sql;
