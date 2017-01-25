// ChildNode.remove() polyfill for Internet Explorer
// from: https://github.com/jserz/js_piece/blob/master/DOM/ChildNode/remove()/remove().md
(function (arr) {
  arr.forEach(function (item) {
    item.remove = item.remove || function () {
      this.parentNode.removeChild(this);
    };
  });
})([Element.prototype, CharacterData.prototype, DocumentType.prototype]);


Vue.component('ManifestView', {
  props: ['manifest', 'width'],
  template: `
  <div class="column" :class="columnWidth">
    <div class="card manifest-view">
      <div class="card-content">
        <div class="media">
          <div class="media-left">
            <figure class="image manifest-preview">
              <a :href="viewerUrl" target="_blank">
                <img :src="manifest.thumbnail" alt="Preview">
              </a>
            </figure>
          </div>
          <div class="media-content">
            <p class="title is-5 manifest-label">{{ truncatedLabel }}</p>
            <p class="subtitle is-6">
              <img class="attribution-logo" :src="manifest.logo">
              <span v-html="manifest.attribution" />
            </p>
          </div>
        </div>
      </div>
      <div class="card-footer">
        <a class="card-footer-item" :href="manifest['@id']">
          <img src="/static/img/iiif_128.png" alt="IIIF Manifest">
        </a>
        <a v-if="manifest.metsurl" class="card-footer-item" :href="manifest.metsurl">
          <img src="/static/img/mets.png" alt="METS XML">
        </a>
        <a class="card-footer-item button is-primary" :href="viewerUrl"
           target="_blank">View</a>
      </div>
    </div>
  </div>`,
  computed: {
    columnWidth: function() {
      return `is-${this.width || 4}`;
    },
    viewerUrl: function() {
      return `/view/${this.manifest['@id'].split('/').slice(-2)[0]}`;
    },
    truncatedLabel: function() {
      if (this.manifest.label.length < 100) {
        return this.manifest.label;
      } else {
        var parts = this.manifest.label.split(" ");
        var label = "";
        while (label.length < 100) {
          var part = parts.shift();
          if ((label.length + part.length) > 100) {
            label += '…';
            break;
          }
          label += (" " + part);
        }
        return label;
      }
    }
  }
});


Vue.component('Pagination', {
  props: ['prev', 'next', 'total', 'startIndex', 'perPage'],
  template: `
    <nav class="pagination is-centered">
      <a class="pagination-previous" @click="onPrevious"
         :class="{'is-disabled': !prev}">
        Previous
      </a>
      <span class="page-indicator">
        {{ startIndex + 1 }} - {{ pageEndIndex }} / {{ total }}
      </span>
      <a class="pagination-next" @click="onNext"
         :class="{'is-disabled': !next}">
        Next
      </a>
    </nav>`,
  methods: {
    onNext: function() {
      var vm = this;
      axios.get(this.next)
        .then(function(response) {
          vm.$emit('change-page', response.data);
        });
    },
    onPrevious: function() {
      var vm = this;
      axios.get(this.prev)
        .then(function(response) {
          vm.$emit('change-page', response.data);
        });
    }
  },
  computed: {
    pageEndIndex: function() {
      return this.startIndex + this.perPage;
    }
  }
});


Vue.component('PageDisplay', {
  props: ['prev', 'next', 'total', 'startIndex', 'perPage'],
  template: `
    <div class="current-page">
      <Pagination :prev="prev" :next="next" :total="total"
                  :startIndex="startIndex" :perPage="perPage"
                  @change-page="onPageChange" />
      <div class="container columns is-multiline">
        <slot />
      </div>
      <Pagination :prev="prev" :next="next" :total="total"
                  :startIndex="startIndex" :perPage="perPage"
                  @change-page="onPageChange" />
      <div class="container columns is-multiline">
    </div>`,
  methods: {
    onPageChange: function(page) {
      this.$emit('change-page', page);
    }
  }
});
