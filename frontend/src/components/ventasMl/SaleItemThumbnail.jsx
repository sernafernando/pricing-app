import { useState } from 'react';
import styles from './SaleItemThumbnail.module.css';

/**
 * The thumbnail box of an item sold, for Ventas ML's row (`ProductCell`) and panels (`ProductSection`,
 * `PackDetailPanel`): the first stored photo of the MLA sold (`thumbnail_url`, the backend's `_thumbnails_by_mla`),
 * shown from its stored URL as is, never downloaded or proxied. Without one, or when it fails to load, the box keeps
 * the caller's placeholder (`children`: the category icon or `Package`). The caller sizes and frames the box with
 * `className`; the photo fills it. `alt` is what the photo announces: in the row it takes the category icon's job
 * (the category), in the panels it is decorative (empty) since the item's title sits beside it.
 *
 * @param {object} props
 * @param {string | null} [props.url] The MLA's stored photo.
 * @param {string} [props.alt] What the photo announces; empty: decorative.
 * @param {string} [props.className] The box's own styles.
 * @param {import('react').ReactNode} props.children The placeholder.
 */
export default function SaleItemThumbnail({ url, alt = '', className = '', children, ...rest }) {
  // The URL that failed: another URL (a different item in the same box) is tried again.
  const [failedUrl, setFailedUrl] = useState(null);
  const showPhoto = Boolean(url) && failedUrl !== url;
  return (
    <div className={`${className} ${styles.box}`} data-sale-item-placeholder={showPhoto ? undefined : ''} {...rest}>
      {showPhoto ? (
        <img className={styles.photo} src={url} alt={alt} loading="lazy" decoding="async" onError={() => setFailedUrl(url)} />
      ) : (
        children
      )}
    </div>
  );
}
