import { describe, expect, it } from "vitest";
import { inviteTokenFromPath } from "./Invites";

describe("inviteTokenFromPath", () => {
  it("reads the token from /invite/<token>", () => {
    expect(inviteTokenFromPath("/invite/abc-123_XYZ")).toBe("abc-123_XYZ");
    expect(inviteTokenFromPath("/invite/abc-123_XYZ/")).toBe("abc-123_XYZ");
  });

  it("decodes percent-escapes and survives malformed ones", () => {
    expect(inviteTokenFromPath("/invite/a%2Fb")).toBe("a/b");
    expect(inviteTokenFromPath("/invite/100%")).toBe("100%");
  });

  it("is null for any other path", () => {
    expect(inviteTokenFromPath("/")).toBeNull();
    expect(inviteTokenFromPath("/invites/abc")).toBeNull();
    expect(inviteTokenFromPath("/pair")).toBeNull();
  });
});
