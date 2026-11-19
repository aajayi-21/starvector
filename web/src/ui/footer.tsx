/**
 * The site footer (spec F1): the brand, and the ways out of the app —
 * the About page, the Releases page, and the source on GitHub. It sits
 * at the end of each screen but the two drawing screens, signed in or
 * not.
 *
 * It is a `footer` and not a `nav`: the app has one navigation, the
 * five places, in the top bar and the tab bar. It holds fixed text
 * alone, thus it reads nothing from the server and shows nothing of a
 * day (spec W1 §8).
 */

import { ArrowUpRight, GithubLogo } from "@phosphor-icons/react";
import { Link } from "@tanstack/react-router";

import { LogoMark } from "./logo";
import { GITHUB_URL } from "./site-links";

export function SiteFooter(props: {
  /** True below the phone tab bar, which the footer must clear. */
  tabBar?: boolean;
}): React.JSX.Element {
  return (
    <footer
      className={
        props.tabBar === true ? "site-footer site-footer-tabbar" : "site-footer"
      }
    >
      <div className="site-footer-inner">
        <p className="site-footer-brand">
          <LogoMark size={18} />
          <span>
            <span className="site-footer-name">Starvector</span> — a new photo
            every day
          </span>
        </p>
        {/* The email-updates box goes here, between the brand and the
            links, when the owner rules where the addresses go (spec F1
            §4). Nothing renders for it today. */}
        <ul className="site-footer-links">
          <li>
            <Link to="/about">About</Link>
          </li>
          <li>
            <Link to="/releases">Releases</Link>
          </li>
          <li>
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">
              <GithubLogo size={16} aria-hidden="true" />
              GitHub
              <ArrowUpRight size={13} aria-hidden="true" />
              <span className="visually-hidden"> (opens in a new tab)</span>
            </a>
          </li>
        </ul>
      </div>
    </footer>
  );
}
