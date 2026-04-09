import createMiddleware from "next-intl/middleware";
import { routing } from "./src/i18n/routing";

export default createMiddleware(routing);

export const config = {
  matcher: [
    // Match all pathnames except /api, /_next, /_vercel, static files
    "/((?!api|_next|_vercel|.*\\..*).*)",
  ],
};
