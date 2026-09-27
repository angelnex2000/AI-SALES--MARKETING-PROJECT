import { redirect } from "next/navigation";

// Root: send visitors into the app. middleware / the mock-auth flag decide
// whether they land on the dashboard or get bounced to /login.
export default function Home() {
  redirect("/dashboard");
}
